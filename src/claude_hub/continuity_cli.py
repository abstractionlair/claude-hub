"""CLI entrypoint for the continuity module.

Delegates to continuity.main(). Exists so that
`python3 -m claude_hub.continuity` works via the __main__.py pattern
without modifying any existing __main__.py.
"""

from claude_hub.continuity import main

if __name__ == "__main__":
    main()
