# Event filters

Structural-risk terms such as fraud, DOJ investigations, accounting restatements, bankruptcy risk, and major regulatory shocks are hard vetoes for premium candidates. Earnings are also excluded within three calendar days unless a separately approved event strategy is implemented. The LLM may explain or escalate these decisions, but cannot override them.

The live-cycle CSV adapter uses `date,symbol,structural_risk` rows. The checked-in file under `data/events/news.csv` is an empty schema template; it is not a news feed and cannot support a performance claim until dated events are ingested.
