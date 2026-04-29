import multiprocessing

from doc_ingest.desktop_backend import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
