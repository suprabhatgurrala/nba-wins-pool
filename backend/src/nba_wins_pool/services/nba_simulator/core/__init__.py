"""Pure NBA season simulator: Monte Carlo regular season, NBA Cup, play-in, playoffs.

This package must stay free of I/O and app dependencies. It only imports the
standard library, numpy, pandas, scipy, and other ``core`` modules
(``tests/test_nba_simulator_core_boundary.py`` enforces this). Inputs are plain
DataFrames, arrays and dicts (see :mod:`.schedule` for the schedule contract);
fetching data and persisting results belong to the adapters one level up
(``data.py``, ``nba_simulator_service.py``).
"""
