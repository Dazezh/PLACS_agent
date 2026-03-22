# Windows Admin Service

- GUI checks the Windows helper service on startup.
- If the service is missing or broken, the fullscreen setup flow appears.
- Privileged Windows actions go through one approval dialog and then through the local helper service.
- The helper service executes a whole action sequence at once, so VPN connect no longer causes two separate UAC prompts.
