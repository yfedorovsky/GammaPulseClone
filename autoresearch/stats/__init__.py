"""Vendored statistical core for the AutoResearch deflation engine.

These modules implement the deflation/overfitting stack from Bailey & Lopez de
Prado et al. directly (with paper citations + reference-value tests), because the
named libraries are not installable here: ``pypbo`` is GitHub-only/unmaintained
and ``mlfinlab`` went commercial (pulled from PyPI). Only ``arch`` (Hansen SPA)
is an external dependency. See ``autoresearch/requirements.txt`` for the decision.

Modules:
  deflated_sharpe  - PSR, E[max Sharpe | N], DSR, MinTRL, MinBTL.
  cscv_pbo         - Combinatorially-Symmetric Cross-Validation -> PBO.
  cpcv             - purged + embargoed combinatorial cross-validation splits.
  spa              - thin wrapper over arch.bootstrap.SPA (beat-the-baseline test).
"""
