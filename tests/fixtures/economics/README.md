# Synthetic ETF economics fixture

Every value in this fixture is synthetic and non-official. It is test input only;
it is not evidence about IE00B5BMR087 or any other real ETF. The identifier is
used only to exercise the requested production path. The arbitrary benchmark,
prices, fees, assets, flows, source IDs, and corporate-action coverage below do
not describe a real instrument or provider.

`manifest.json` identifies the synthetic disclosure checksum and synthetic
corporate-action coverage records. `economics.csv` and `prices.csv` are consumed
by production loaders in the focused integration tests. `closure-merger.csv`
contains a synthetic share-class merger observation and successor identity;
it is used only by the bounded closure regression test.
