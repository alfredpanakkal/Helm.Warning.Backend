# Universal-parser fixtures

Trimmed excerpts of the October 2026 live coordinator bulletins
(regions II, III, V, VI, VII, IX, X, XIII, XIV, XV, XVI, XVII, XVIII, XIX, XX),
used by `tests/test_universal_formats.py`. Each file keeps the region's real
header and coordinate quirks: 4-digit years (II/XVII/XVIII), bare `0648/26`
headers (V), `NAVAREA - 0355-2026` (VI), `n OF yyyy` (VII), DMS seconds
(XIII/XVI), `LAT./LONG.` wording (XV), `Number:n/yy` anchors (XIX), and
broadcast tails `NNNN` / `.=` (X, XIV, XX).

Do not reformat these files — the tests assert exact parsed coordinates,
block counts, and header styles against them.