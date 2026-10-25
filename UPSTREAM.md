# Upstream dependency and attribution

This standalone application depends on a separate local checkout of
[OpenPoke](https://github.com/shlokkhemani/openpoke), commit
`5b5f635935a64ab37884c025d70abb0ed731c094`, by Shlok Khemani, MIT licensed.
The full checkout is not bundled. `integration/openpoke-runtime.patch` derives from
that runtime and adds scoped dependency injection, observable tools and failure state.
The MIT license is retained in LICENSE. The host adapter imports upstream execution
classes; the routing app and frontend remain independently authored and runnable.

Problem context: https://www.shloked.com/writing/openpoke.
No changes were pushed to the upstream repository.
