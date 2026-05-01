import sys
import shlex
import types
import importlib

# Python 3.13 compatibility shim for mrjob < 0.7.5
if "pipes" not in sys.modules:
    _pipes = types.ModuleType("pipes")
    setattr(_pipes, "quote", shlex.quote)
    sys.modules["pipes"] = _pipes

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m cc_feeds.mrjob_wrapper <module_name> [args...]")
        sys.exit(1)
    
    module_name = sys.argv[1]
    # Remove the wrapper and module name from sys.argv
    sys.argv = sys.argv[1:]
    
    # Import and run the tool's main
    try:
        module = importlib.import_module(module_name)
        if hasattr(module, "main"):
            module.main()
        else:
            # Some tools might not have main()
            pass
    except ImportError as e:
        print(f"Error importing {module_name}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
