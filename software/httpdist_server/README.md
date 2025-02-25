# pytest-httpdist

This plugin is used to distribute tests over multiple workers, via an HTTP server.

## Parts

1. One `pytest` plugin running as a "requester"
2. Greater than one `pytest` plugin running as "worker" nodes
3. A server that proxies requested tests from the "requester" node to appropriate "worker" nodes
4. A bootstrap application whose job is to spool up worker nodes. It's responsible for:
  - Polling the server for sessions
  - Starting a worker for a session with a command passed to it by the server
  - Killing a worker if a session is aborted
