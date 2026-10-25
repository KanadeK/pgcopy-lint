# Third-party materials

Application code and synthetic test fixtures are original to this project and
released under MIT. No third-party source code or data is vendored.

The Python standard library is provided by the user's Python distribution under
the PSF license. SQLite, where used, is provided by that distribution and is in
the public domain. Development/build tools (setuptools and build: MIT; Ruff: MIT)
are not runtime dependencies or bundled in release wheels. GitHub Actions are
referenced, not vendored. Documentation links identify the external specifications
used to implement the formats; no external documentation is copied into the code.

Optional server tests use Psycopg 3 (LGPL-3.0-or-later) and its binary distribution,
and the official PostgreSQL container (PostgreSQL License and bundled component
licenses). These are installed separately for testing, never vendored or included
in the application wheel. The application remains standard-library-only.
