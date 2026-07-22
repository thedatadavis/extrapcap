from dataclasses import dataclass


@dataclass
class SleeveLedger:
    premium_collected: float = 0.0
    asymmetric_budget: float = 0.0
    asymmetric_deployed: float = 0.0
    asymmetric_realized_pnl: float = 0.0
    pending_asymmetric_funding: float = 0.0
    funding_period: str | None = None

    def realize_premium(
        self,
        amount: float,
        funding_pct: float,
        *,
        mode: str = "continuous",
        batch_id: str | None = None,
    ) -> float:
        if amount < 0:
            raise ValueError("realized premium must be non-negative")
        if not 0.10 <= funding_pct <= 0.20:
            raise ValueError("asymmetric funding must be between 10% and 20%")
        if mode not in {"continuous", "batched"}:
            raise ValueError("funding mode must be continuous or batched")
        allocation = amount * funding_pct
        self.premium_collected += amount
        if mode == "continuous":
            self.asymmetric_budget += allocation
            return allocation
        if batch_id is not None and self.funding_period not in {None, batch_id}:
            self.flush_funding_pool()
        self.funding_period = batch_id or self.funding_period
        self.pending_asymmetric_funding += allocation
        return 0.0

    def flush_funding_pool(self) -> float:
        """Transfer only pooled realized premium into the asymmetric budget."""
        amount = self.pending_asymmetric_funding
        self.asymmetric_budget += amount
        self.pending_asymmetric_funding = 0.0
        return amount

    def deploy_asymmetric(self, max_loss: float) -> None:
        if max_loss <= 0 or max_loss > self.asymmetric_budget:
            raise ValueError("asymmetric deployment exceeds funded budget")
        self.asymmetric_budget -= max_loss
        self.asymmetric_deployed += max_loss

    def realize_asymmetric(self, pnl: float) -> None:
        self.asymmetric_realized_pnl += pnl
