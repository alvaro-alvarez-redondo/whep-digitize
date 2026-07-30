"""Stage 0 — setup: constants, config, directories, and shared helpers.

Ports ``r/0-general_pipeline/``. This is the shared foundation every other stage imports:
constants (:mod:`~whep_digitize.setup.constants`), the per-run
:class:`~whep_digitize.setup.config.Config`, runtime
:class:`~whep_digitize.setup.options.RuntimeOptions`, directory construction, and the
:mod:`~whep_digitize.setup.helpers` package.
"""

from __future__ import annotations
