# FVG Alert Bot 1.3.3

Patch release fixes portable verified backups. macOS metadata files (`._*` and
`.DS_Store`) are excluded before archive creation and `tar` runs with
`COPYFILE_DISABLE=1`. The signed manifest remains strict for all ordinary
archive members; unknown runtime files still fail verification.

This release does not enable operational flags, include Telegram Mini App, or
modify production runtime data automatically.
