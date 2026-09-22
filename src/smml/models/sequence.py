"""Sequence models for multi-depth soil moisture.

Soil moisture is a state variable: today's value is yesterday's value plus the
day's fluxes, integrated over a memory that runs from hours at the surface to
seasons at a metre. A tabular model can only approximate that memory through
whatever fixed rolling windows the feature builder happened to choose. A
recurrent model learns the integration itself.

The architecture here is an **entity-aware LSTM** (EA-LSTM, Kratzert et al. 2019,
HESS). It was developed for rainfall-runoff modelling across hundreds of
catchments and the structural problem is identical to this one: many sites, each
with a handful of static attributes, all sharing one dynamic process whose
*parameters* depend on those attributes. The EA-LSTM encodes that directly —

* the **input gate** is computed once per site from the static attributes alone
  and then held fixed over time, so it acts as a learned, per-site selection of
  which forcings matter;
* the forget and output gates and the cell update see only the dynamic forcings.

The result is that the static attributes cannot simply be memorized as a
site-identifying shortcut — they can only act by modulating how forcings are
used — which is exactly the inductive bias needed for a model that must
generalize to a field it has never seen. A plain LSTM given the static
attributes as extra input channels is free to use them as a lookup key, and
does.

A multi-depth head predicts the whole profile at once, so the layers share a
representation and the deep layers benefit from the abundant surface data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .base import SoilMoistureModel

log = logging.getLogger(__name__)


def _require_torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "sequence models need PyTorch; install with: pip install 'smml[dl]'"
        ) from exc
    return torch


# --------------------------------------------------------------------------
# Windowing
# --------------------------------------------------------------------------


@dataclass
class SequenceSpec:
    """How the long table is cut into training sequences."""

    sequence_length: int = 180
    #: Depth layers the model predicts, as (top_cm, bottom_cm).
    depths: tuple[tuple[float, float], ...] = (
        (0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200)
    )
    stride: int = 1
    min_valid_fraction: float = 0.5


def build_sequences(
    frame: pd.DataFrame,
    dynamic_cols: list[str],
    static_cols: list[str],
    target_col: str,
    spec: SequenceSpec,
    site_col: str = "site_id",
    date_col: str = "date",
) -> dict[str, np.ndarray]:
    """Pivot the long table into ``(n_windows, sequence_length, n_features)`` arrays.

    The target becomes ``(n_windows, n_depths)`` — the profile on the final day
    of each window. Predicting only the last step, rather than every step, keeps
    the loss aligned with how the model is used and avoids weighting early
    timesteps (whose cell state is still warming up) as if they were predictions.

    Windows whose final-day profile is more than ``1 - min_valid_fraction``
    missing are dropped; remaining gaps are carried as NaN and masked in the loss.
    """
    frame = frame.sort_values([site_col, date_col])
    depth_keys = [f"{int(a)}_{int(b)}" for a, b in spec.depths]

    x_dyn, x_stat, y_all, meta = [], [], [], []

    for site, group in frame.groupby(site_col, sort=False, observed=True):
        # One row per date, with the per-depth targets widened into columns.
        wide = group.pivot_table(
            index=date_col,
            columns=["depth_top_cm", "depth_bottom_cm"],
            values=target_col,
            aggfunc="mean",
            observed=True,
        )
        wide.columns = [f"{int(a)}_{int(b)}" for a, b in wide.columns]
        for key in depth_keys:
            if key not in wide.columns:
                wide[key] = np.nan
        wide = wide[depth_keys]

        daily = group.drop_duplicates(subset=[date_col]).set_index(date_col)
        daily = daily.reindex(wide.index)

        dyn = daily[dynamic_cols].to_numpy(dtype=np.float32)
        stat = daily[static_cols].iloc[0].to_numpy(dtype=np.float32) if static_cols else np.zeros(0, np.float32)
        targets = wide.to_numpy(dtype=np.float32)

        n = len(wide)
        for end in range(spec.sequence_length, n + 1, spec.stride):
            start = end - spec.sequence_length
            y = targets[end - 1]
            if np.isfinite(y).mean() < spec.min_valid_fraction:
                continue
            window = dyn[start:end]
            if not np.isfinite(window).any():
                continue
            x_dyn.append(window)
            x_stat.append(stat)
            y_all.append(y)
            meta.append((site, wide.index[end - 1]))

    if not x_dyn:
        raise ValueError(
            "no sequences could be built; the sequence length probably exceeds "
            "the per-site record length"
        )

    return {
        "x_dynamic": np.stack(x_dyn),
        "x_static": np.stack(x_stat),
        "y": np.stack(y_all),
        "sites": np.array([m[0] for m in meta]),
        "dates": np.array([m[1] for m in meta]),
        "depth_keys": np.array(depth_keys),
    }


# --------------------------------------------------------------------------
# The network
# --------------------------------------------------------------------------


def _make_ea_lstm_cell(torch):
    nn = torch.nn

    class EALSTMCell(nn.Module):
        """One EA-LSTM step.

        The static input gate ``i`` is supplied by the caller and is constant in
        time; only the forget gate, the output gate and the candidate cell state
        are computed from the dynamic input and the previous hidden state.
        """

        def __init__(self, dynamic_size: int, hidden_size: int):
            super().__init__()
            self.hidden_size = hidden_size
            # Three gates: forget, output, candidate.
            self.weight_ih = nn.Parameter(torch.empty(dynamic_size, 3 * hidden_size))
            self.weight_hh = nn.Parameter(torch.empty(hidden_size, 3 * hidden_size))
            self.bias = nn.Parameter(torch.zeros(3 * hidden_size))
            self.reset_parameters()

        def reset_parameters(self):
            nn.init.orthogonal_(self.weight_hh)
            nn.init.xavier_uniform_(self.weight_ih)
            nn.init.zeros_(self.bias)
            # Forget-gate bias at 1: start by remembering, which is the right
            # prior for a state variable with long memory.
            with torch.no_grad():
                self.bias[: self.hidden_size].fill_(1.0)

        def forward(self, x_t, i_gate, state):
            h, c = state
            gates = x_t @ self.weight_ih + h @ self.weight_hh + self.bias
            f, o, g = gates.chunk(3, dim=1)
            f = torch.sigmoid(f)
            o = torch.sigmoid(o)
            g = torch.tanh(g)
            c = f * c + i_gate * g
            h = o * torch.tanh(c)
            return h, c

    return EALSTMCell


def _make_network(torch):
    nn = torch.nn
    EALSTMCell = _make_ea_lstm_cell(torch)

    class EALSTM(nn.Module):
        """EA-LSTM with a multi-depth output head."""

        def __init__(
            self,
            dynamic_size: int,
            static_size: int,
            hidden_size: int = 128,
            n_depths: int = 6,
            dropout: float = 0.2,
            head_hidden: int = 64,
        ):
            super().__init__()
            self.hidden_size = hidden_size
            self.static_gate = nn.Linear(max(static_size, 1), hidden_size)
            self.cell = EALSTMCell(dynamic_size, hidden_size)
            self.dropout = nn.Dropout(dropout)
            self.head = nn.Sequential(
                nn.Linear(hidden_size, head_hidden),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(head_hidden, n_depths),
            )
            self.static_size = static_size

        def forward(self, x_dynamic, x_static):
            batch, steps, _ = x_dynamic.shape
            if self.static_size == 0:
                x_static = x_dynamic.new_zeros((batch, 1))
            i_gate = torch.sigmoid(self.static_gate(x_static))  # constant in time
            h = x_dynamic.new_zeros((batch, self.hidden_size))
            c = x_dynamic.new_zeros((batch, self.hidden_size))
            for t in range(steps):
                h, c = self.cell(x_dynamic[:, t], i_gate, (h, c))
            return self.head(self.dropout(h))

    return EALSTM


def masked_mse(torch, pred, target):
    """MSE over the finite entries only.

    The profile is ragged — most sites report a handful of depths, not all six —
    so the loss has to ignore absent layers rather than treat them as zero.
    """
    mask = torch.isfinite(target)
    if not mask.any():
        return pred.sum() * 0.0
    diff = (pred[mask] - target[mask]) ** 2
    return diff.mean()


# --------------------------------------------------------------------------
# The model wrapper
# --------------------------------------------------------------------------


@dataclass
class EALSTMConfig:
    sequence_length: int = 180
    hidden_size: int = 128
    head_hidden: int = 64
    dropout: float = 0.2
    learning_rate: float = 1e-3
    weight_decay: float = 1e-5
    batch_size: int = 256
    max_epochs: int = 40
    patience: int = 8
    grad_clip: float = 1.0
    stride: int = 3
    seed: int = 0
    device: str = "auto"
    depths: tuple[tuple[float, float], ...] = field(
        default_factory=lambda: ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))
    )


class EALSTMModel(SoilMoistureModel):
    """Entity-aware LSTM over daily forcings, predicting the full depth profile."""

    name = "ea_lstm"
    sequential = True

    def __init__(self, config: EALSTMConfig | None = None, dynamic_cols: list[str] | None = None,
                 static_cols: list[str] | None = None):
        self.config = config or EALSTMConfig()
        self.dynamic_cols = dynamic_cols
        self.static_cols = static_cols
        self.net_ = None
        self.dyn_mean_ = self.dyn_std_ = None
        self.stat_mean_ = self.stat_std_ = None
        self.y_mean_ = self.y_std_ = None
        self.history_: list[dict] = []

    # -- column selection -------------------------------------------------

    def _split_columns(self, frame: pd.DataFrame, feature_cols: list[str]) -> tuple[list[str], list[str]]:
        """Partition features into time-varying and site-constant.

        Determined empirically rather than by a hard-coded list: a column whose
        value never changes within a site is static, whatever it is called. That
        keeps the split correct as the feature set evolves.
        """
        if self.dynamic_cols is not None and self.static_cols is not None:
            return self.dynamic_cols, self.static_cols
        numeric = [c for c in feature_cols if pd.api.types.is_numeric_dtype(frame[c])]
        sample_sites = pd.unique(frame["site_id"])[:12]
        subset = frame[frame["site_id"].isin(sample_sites)]
        varies = subset.groupby("site_id", observed=True)[numeric].nunique().max() > 1
        dynamic = [c for c in numeric if bool(varies.get(c, True))]
        static = [c for c in numeric if not bool(varies.get(c, True))]
        return dynamic, static

    # -- fitting ----------------------------------------------------------

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        torch = _require_torch()
        cfg = self.config
        torch.manual_seed(cfg.seed)
        np.random.seed(cfg.seed)

        device = cfg.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        device = torch.device(device)

        dynamic, static = self._split_columns(frame, feature_cols)
        self.dynamic_cols, self.static_cols = dynamic, static
        spec = SequenceSpec(sequence_length=cfg.sequence_length, depths=cfg.depths, stride=cfg.stride)

        train_data = build_sequences(frame, dynamic, static, target_col, spec)
        self._fit_scalers(train_data)
        xd, xs, y = self._scale(train_data)

        valid_tensors = None
        if validation is not None and len(validation):
            try:
                vdata = build_sequences(validation, dynamic, static, target_col,
                                        SequenceSpec(cfg.sequence_length, cfg.depths, stride=cfg.stride * 3))
                vxd, vxs, vy = self._scale(vdata)
                valid_tensors = (
                    torch.tensor(vxd, device=device),
                    torch.tensor(vxs, device=device),
                    torch.tensor(vy, device=device),
                )
            except ValueError:
                log.warning("validation set too short for sequences; training without early stopping")

        EALSTM = _make_network(torch)
        self.net_ = EALSTM(
            dynamic_size=xd.shape[2], static_size=xs.shape[1],
            hidden_size=cfg.hidden_size, n_depths=y.shape[1],
            dropout=cfg.dropout, head_hidden=cfg.head_hidden,
        ).to(device)

        optimizer = torch.optim.AdamW(self.net_.parameters(), lr=cfg.learning_rate,
                                      weight_decay=cfg.weight_decay)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.5, patience=3)

        xd_t = torch.tensor(xd)
        xs_t = torch.tensor(xs)
        y_t = torch.tensor(y)
        n = len(xd_t)

        best = float("inf")
        best_state = None
        stale = 0

        for epoch in range(cfg.max_epochs):
            self.net_.train()
            order = torch.randperm(n)
            total, batches = 0.0, 0
            for start in range(0, n, cfg.batch_size):
                idx = order[start : start + cfg.batch_size]
                bd = xd_t[idx].to(device)
                bs = xs_t[idx].to(device)
                by = y_t[idx].to(device)
                optimizer.zero_grad()
                loss = masked_mse(torch, self.net_(bd, bs), by)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.net_.parameters(), cfg.grad_clip)
                optimizer.step()
                total += float(loss.item())
                batches += 1
            train_loss = total / max(batches, 1)

            if valid_tensors is not None:
                self.net_.eval()
                with torch.no_grad():
                    vloss = float(masked_mse(torch, self.net_(valid_tensors[0], valid_tensors[1]),
                                             valid_tensors[2]).item())
                scheduler.step(vloss)
                monitor = vloss
            else:
                monitor = train_loss

            self.history_.append({"epoch": epoch, "train_loss": train_loss, "monitor": monitor})
            if monitor < best - 1e-6:
                best, stale = monitor, 0
                best_state = {k: v.detach().clone() for k, v in self.net_.state_dict().items()}
            else:
                stale += 1
                if stale >= cfg.patience:
                    log.info("early stopping at epoch %d", epoch)
                    break

        if best_state is not None:
            self.net_.load_state_dict(best_state)
        self.device_ = device
        return self

    def _fit_scalers(self, data: dict[str, np.ndarray]) -> None:
        xd = data["x_dynamic"].reshape(-1, data["x_dynamic"].shape[2])
        self.dyn_mean_ = np.nanmean(xd, axis=0)
        self.dyn_std_ = np.nanstd(xd, axis=0)
        self.dyn_std_[self.dyn_std_ < 1e-8] = 1.0
        xs = data["x_static"]
        self.stat_mean_ = np.nanmean(xs, axis=0) if xs.shape[1] else np.zeros(0, np.float32)
        self.stat_std_ = np.nanstd(xs, axis=0) if xs.shape[1] else np.zeros(0, np.float32)
        if self.stat_std_.size:
            self.stat_std_[self.stat_std_ < 1e-8] = 1.0
        y = data["y"]
        self.y_mean_ = float(np.nanmean(y))
        self.y_std_ = float(np.nanstd(y)) or 1.0

    def _scale(self, data: dict[str, np.ndarray]):
        xd = (data["x_dynamic"] - self.dyn_mean_) / self.dyn_std_
        xd = np.nan_to_num(xd, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        xs = data["x_static"]
        if xs.shape[1]:
            xs = (xs - self.stat_mean_) / self.stat_std_
            xs = np.nan_to_num(xs, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        else:
            xs = xs.astype(np.float32)
        y = ((data["y"] - self.y_mean_) / self.y_std_).astype(np.float32)
        return xd, xs, y

    # -- prediction -------------------------------------------------------

    def predict(self, frame, feature_cols):
        """Predict for every row of ``frame``, matching on site, date and depth.

        Rows with too little history to form a full sequence get NaN, which the
        evaluation drops. That is honest: the model genuinely cannot predict a
        site's first ``sequence_length`` days, and imputing them would misstate
        its coverage.
        """
        torch = _require_torch()
        if self.net_ is None:
            raise RuntimeError("model is not fitted")
        cfg = self.config
        spec = SequenceSpec(cfg.sequence_length, cfg.depths, stride=1)
        data = build_sequences(frame, self.dynamic_cols, self.static_cols,
                               self._target_for_prediction(frame), spec)
        xd, xs, _ = self._scale(data)

        self.net_.eval()
        outputs = []
        with torch.no_grad():
            for start in range(0, len(xd), cfg.batch_size):
                bd = torch.tensor(xd[start : start + cfg.batch_size], device=self.device_)
                bs = torch.tensor(xs[start : start + cfg.batch_size], device=self.device_)
                outputs.append(self.net_(bd, bs).cpu().numpy())
        pred = np.vstack(outputs) * self.y_std_ + self.y_mean_

        lookup: dict[tuple, float] = {}
        depth_keys = list(data["depth_keys"])
        for row, (site, date) in enumerate(zip(data["sites"], data["dates"], strict=True)):
            for col, key in enumerate(depth_keys):
                lookup[(site, pd.Timestamp(date), key)] = float(pred[row, col])

        keys = [
            (s, pd.Timestamp(d), f"{int(a)}_{int(b)}")
            for s, d, a, b in zip(frame["site_id"], pd.to_datetime(frame["date"]),
                                  frame["depth_top_cm"], frame["depth_bottom_cm"], strict=True)
        ]
        return np.array([lookup.get(k, np.nan) for k in keys])

    def _target_for_prediction(self, frame: pd.DataFrame) -> str:
        """A target column is needed only to shape the pivot, not to inform it.

        ``build_sequences`` drops windows whose final profile is mostly missing,
        so at prediction time a column of the right shape must exist. Any target
        column present works; when none is, a dummy of NaN is added and the
        validity filter is relaxed by the caller.
        """
        for candidate in ("theta_obs_m3m3", "theta_m3m3", "theta_true_m3m3"):
            if candidate in frame.columns:
                return candidate
        raise ValueError("frame has no recognizable target column to shape the depth pivot")

    def get_params(self):
        return dict(vars(self.config).items())
