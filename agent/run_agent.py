"""PyInstaller entry point (absolute imports; the package __main__ uses relative imports)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from pocketdesk_agent.main import main
    main()
