# Regreso de rendimiento: first-rule-wins por descomposición de grupos

Fecha: 2026-09-09
Estado: investigado, no resuelto
Impacto: pipeline pasa de ~93s a 20+ minutos (15x+ más lento)

## Resumen ejecutivo

El parche de first-rule-wins implementado mediante descomposición de grupos (`_decompose_group`)
causó un regresión catastrófica de rendimiento: **225x más lento** en el archivo de reglas más
grande (clean_commodity), con una expansión de **15 grupos → 810 grupos** (54x).

La causa raíz es **estructural**: la descomposición convierte un único join vectorizado en cientos
de joins pequeños con overhead de Python entre cada uno, repitiendo trabajo O(N) innecesariamente.

## Qué se implementó

### Ubicación del cambio

- **Archivo**: `src/whep_digitize/postpro/rule_engine/schema_validation.py`
- **Función nueva**: `_decompose_group()` (líneas ~405-455)
- **Llamador**: `build_conditional_rule_dictionary()` ahora llama a `_decompose_group()` para cada grupo

### Mecanismo

Cuando un grupo tiene reglas con `value_source_raw` duplicado (colisión), `_decompose_group`:
1. Detecta los valores de `value_source_raw` que aparecen más de una vez
2. Separa cada regla colisionante en su propio sub-grupo de una sola regla
3. Las reglas no-colisionantes permanecen juntas en un único sub-grupo

### Ejemplo concreto

Archivo `clean_commodity.xlsx`, hoja `commodity_footnote`:
- 768 reglas, 1 grupo `(commodity, footnotes)`
- 718 valores de `value_source_raw` duplicados
- Resultado: **718 sub-grupos** (717 de 1 regla + 1 de 51 reglas no-colisionantes)

Total clean rules (todos los archivos):
- 1,215 reglas, 15 grupos originales
- **810 sub-grupos** después de descomposición (54x expansión)

## Flujo de ejecución afectado

### Antes (17 grupos)

```
for group in plan.grouped_dictionary:  # 17 iteraciones
    apply_conditional_rule_group(dataset, group)
    # Dentro de apply_conditional_rule_group:
    #   1. _build_normalize_rules(group)        # normaliza M reglas
    #   2. _explode_source_candidates(source)    # tokeniza N filas
    #   3. cartesian join candidates × M rules   # O(N×M) vectorizado
    #   4. sort by (row_id, token_index, order)  # O(N×M log(N×M)) vectorizado
    #   5. match_target_condition_token_map()    # O(N×M) vectorizado
    #   6. _apply_source_rewrite()               # O(matched) Python loop
    #   7. _apply_target_token_rewrite()         # O(matched) Python loop
```

### Después (810 grupos)

```
for group in plan.grouped_dictionary:  # 810 iteraciones
    apply_conditional_rule_group(dataset, group)
    # Dentro de apply_conditional_rule_group:
    #   1. _build_normalize_rules(group)        # normaliza 1 regla (en 797/810 casos)
    #   2. _explode_source_candidates(source)    # tokeniza N filas (¡MISMO source!)
    #   3. cartesian join candidates × 1 rule    # O(N) vectorizado
    #   4. sort by (row_id, token_index, order)  # O(N log N) vectorizado
    #   5. match_target_condition_token_map()    # O(N) vectorizado
    #   6. _apply_source_rewrite()               # O(matched) Python loop
    #   7. _apply_target_token_rewrite()         # O(matched) Python loop
```

## Análisis de rendimiento

### Benchmark: commodity_footnote, 3,000 filas

| Métrica | Antes (1 grupo) | Después (718 sub-grupos) | Ratio |
|---------|-----------------|--------------------------|-------|
| Tiempo total | 46.3 ms | 10,446 ms | **225x** |
| `_explode_source_candidates` | 1x | 718x | 718x |
| `_build_normalize_rules` | 1x (768 reglas) | 718x (1 regla) | 718x |
| join + sort | 1x (3000×768) | 718x (3000×1) | 718x iteraciones |
| target condition match | 1x | 718x | 718x |

### Coste por sub-grupo (3,000 filas)

| Fase | Tiempo por iteración |
|------|---------------------|
| `_explode_source_candidates` | 5.1 ms |
| `_build_normalize_rules` | 2.4 ms |
| join + sort | 0.6 ms |
| target condition match | ~5 ms |
| **Total por sub-grupo** | **~14.5 ms** |

El overhead de Python (llamadas a función, creación de DataFrames, lookups de columnas)
domina el coste por iteración. Con 718 iteraciones, el overhead acumulado es ~10.4s.

### Extrapolación al dataset real (~794,799 filas)

- Factor de escala: 794,799 / 3,000 = 265x
- Tiempo estimado (solo commodity_footnote): 10.4s × 265 = **2,767s (~46 min)**
- Con múltiples archivos de reglas y múltiples passes: **horas**

## Causa raíz profunda

### El problema no es algebraico, es de ejecución

El trabajo algebraico total es similar:
- **Antes**: 1 × O(N × M) = O(N × M)
- **Después**: 718 × O(N × 1) = O(718 × N) ≈ O(N × M) (M=768)

La diferencia es **dónde se ejecuta el trabajo**:
- **Antes**: Un único join de Polars (vectorizado en Rust) procesa N×M filas de golpe
- **Después**: 718 joins pequeños, cada uno con overhead de Python entre ellos

### Trabajo repetido innecesariamente

Cada iteración de sub-grupo repite:
1. **Tokenización del mismo source column** (`_explode_source_candidates`): 718 veces en lugar de 1
2. **Normalización de reglas**: 718 llamadas en lugar de 1 (aunque con 1 regla cada una)
3. **Evaluación de target condition**: 718 veces sobre las mismas filas del dataset

### Por qué el overhead de Python domina

Cada iteración de `apply_conditional_rule_group` tiene:
- ~15-20 llamadas a métodos de Polars (join, sort, filter, select, etc.)
- Creación de múltiples DataFrames temporales
- Lookups de columnas por nombre
- Evaluación de expresiones booleanas complejas
- Construcción de masks

Con 17 grupos, este overhead era irrelevante (17 × ~1ms = 17ms).
Con 810 grupos, el overhead es el dominante (810 × ~14ms = 11.3s).

## Solución correcta (no implementada)

### Enfoque: first-write-wins en los dicts de sustitución

En lugar de descomponer grupos, cambiar la semántica de acumulación en
`_apply_source_rewrite()` y `_apply_target_token_rewrite()`:

**Actual (last-write-wins):**
```python
token_substitutions.setdefault(row_id, {})[token_value] = value
```

**Corrección (first-write-wins):**
```python
subs = token_substitutions.setdefault(row_id, {})
if token_value not in subs:
    subs[token_value] = value
```

### Ventajas de este enfoque

1. **Cero expansión de grupos**: se mantienen los 17 grupos originales
2. **O(1) por sustitución**: una comprobación de diccionario adicional
3. **Mantiene semántica first-rule-wins**: la primera regla en orden de join gana
4. **Superficie de cambio mínima**: ~2 líneas por función
5. **Sin multi-pass retry necesario**: la regla perdedora simplemente no aplica
6. **Rendimiento idéntico al original**: no se añade trabajo repetido

### Por qué se descartó inicialmente

Se consideró "demasiado simple" y se prefirió el enfoque de descomposición por:
- Ser más "explícito" en la intención (grupos sin colisiones)
- Evitar el "dict mutation pattern" que causó el bug original

Pero el análisis de rendimiento demuestra que la simplicidad era la virtud, no el defecto.

## Archivos afectados por la implementación actual

| Archivo | Cambio |
|---------|--------|
| `schema_validation.py` | `_decompose_group()` nuevo, llamado desde `build_conditional_rule_dictionary()` |
| `conditional_group.py` | Solo docstrings (4 ubicaciones) |
| `pipeline-behaviors.md` | D7 reemplazado |
| `deferred-bugs.md` | Entrada de colisiones eliminada |
| `design/first-rule-wins.md` | Documento de diseño nuevo |
| Tests | 4 tests nuevos/modificados |

## Qué necesita hacer la sesión de corrección

1. **Revertir** `_decompose_group()` y su llamada en `build_conditional_rule_dictionary()`
2. **Modificar** `_apply_source_rewrite()` para first-write-wins en `token_substitutions`
3. **Modificar** `_apply_target_token_rewrite()` para first-write-wins en `token_substitutions`
4. **Actualizar** docstrings que mencionan "group decomposition"
5. **Verificar** que los tests existentes siguen pasando
6. **Benchmark** para confirmar retorno a ~93s

## Evidencia

- Benchmark script: ver transcript de la sesión
- Group expansion: 15 → 810 (54x)
- Single file benchmark: 46.3ms → 10,446ms (225x)
- Per sub-group overhead: ~14.5ms
- Extrapolación real dataset: ~46 min solo para commodity_footnote
