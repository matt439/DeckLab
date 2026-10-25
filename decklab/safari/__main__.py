import signal

from .runner import main

# A noninteractive shell can pass ignored SIGINT through exec. The CLI owns
# its interrupt handling; importing runner.main leaves library callers alone.
signal.signal(signal.SIGINT, signal.default_int_handler)
raise SystemExit(main())
