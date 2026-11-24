"""User entry points: ``jobs`` (the ``genkai-surface`` job-file command) and ``setup``
(the installer wizard that ``install.sh`` runs). Methods are started in subprocesses by module
name, so the entry layer does not import builder or screening code directly.
"""
