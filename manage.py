#!/usr/bin/env python
import os
import sys


def main():
    if "DJANGO_SETTINGS_MODULE" not in os.environ:
        default_settings = (
            "config.settings_test"
            if len(sys.argv) > 1 and sys.argv[1] == "test"
            else "config.settings"
        )
        os.environ["DJANGO_SETTINGS_MODULE"] = default_settings
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
