"""Dixon-Coles Poisson model for football goal totals.

Reference: Dixon & Coles (1997), "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market".

For each team we fit attack strength (alpha) and defense strength (beta).
For a home match h vs away a:
    lambda_home = alpha[h] * beta[a] * gamma       (gamma = home advantage)
    lambda_away = alpha[a] * beta[h]
The tau() correction handles the dependency between low scores
(0-0, 1-0, 0-1, 1-1) via a single rho parameter.

Fitting is maximum likelihood with exponential time decay
(weight = exp(-decay * days_since_last_match)), using gradient ascent on
analytic gradients in log space. Pure stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from edge_model.data.football_data import Match

MAX_GOALS = 12  # cap for the score matrix


@dataclass(frozen=True, slots=True)
class TeamModel:
    attack: dict[str, float]  # team -> alpha (relative to league avg = 1.0)
    defense: dict[str, float]  # team -> beta
    gamma: float  # home advantage multiplier
    rho: float  # Dixon-Coles low-score correlation
    base_rate: float  # league-average goals per team (lambda scale)
    fitted_date: date


@dataclass(frozen=True, slots=True)
class ScoreProb:
    home_goals: int
    away_goals: int
    prob: float


def _log_factorial(n: int) -> float:
    return math.lgamma(n + 1)


def _pois_logpmf(k: int, lam: float) -> float:
    if lam <= 0:
        return -math.inf if k > 0 else 0.0
    return k * math.log(lam) - lam - _log_factorial(k)


def tau_adjust(lambda_h: float, lambda_a: float, x: int, y: int, rho: float) -> float:
    """Dixon-Coles tau correction factor for the four low-score cells."""
    if (x, y) == (0, 0):
        return 1.0 - lambda_h * lambda_a * rho
    if (x, y) == (1, 0):
        return 1.0 + lambda_a * rho
    if (x, y) == (0, 1):
        return 1.0 + lambda_h * rho
    if (x, y) == (1, 1):
        return 1.0 - rho
    return 1.0


def _tau_log_grads(lambda_h: float, lambda_a: float, x: int, y: int, rho: float) -> tuple[float, float, float]:
    """Return (d log tau / d lambda_h, d log tau / d lambda_a, d log tau / d rho)."""
    tau = tau_adjust(lambda_h, lambda_a, x, y, rho)
    if tau <= 0:
        return (0.0, 0.0, 0.0)
    if (x, y) == (0, 0):
        return (-lambda_a * rho / tau, -lambda_h * rho / tau, -lambda_h * lambda_a / tau)
    if (x, y) == (1, 0):
        return (0.0, rho / tau, lambda_a / tau)
    if (x, y) == (0, 1):
        return (rho / tau, 0.0, lambda_h / tau)
    if (x, y) == (1, 1):
        return (0.0, 0.0, -1.0 / tau)
    return (0.0, 0.0, 0.0)


def _match_loglik(
    alpha: dict[str, float],
    beta: dict[str, float],
    gamma: float,
    rho: float,
    m: Match,
) -> float:
    """Weighted log-likelihood of a single match."""
    if m.home not in alpha or m.away not in alpha:
        return 0.0  # unknown team contributes nothing
    lambda_h = alpha[m.home] * beta[m.away] * gamma
    lambda_a = alpha[m.away] * beta[m.home]
    x, y = m.home_goals, m.away_goals
    ll = (
        math.log(max(tau_adjust(lambda_h, lambda_a, x, y, rho), 1e-300))
        + _pois_logpmf(x, lambda_h)
        + _pois_logpmf(y, lambda_a)
    )
    return ll


def fit_model(
    matches: list[Match],
    decay: float = 0.004,
    max_iter: int = 400,
    lr: float = 0.15,
    momentum: float = 0.9,
    eps: float = 1e-8,
    clip_grad: float = 5.0,
    param_clip: float = 4.0,
    eval_every: int = 25,
) -> TeamModel:
    """Fit a Dixon-Coles model to matches via weighted MLE.

    Time decay: match weight = exp(-decay * days since the latest match).
    Parameters are optimized in log space (log alpha, log beta, log gamma),
    then normalized so mean(alpha) = mean(beta) = 1.

    Gradient clipping (clip_grad) and parameter clamping (param_clip) keep
    the optimizer stable on small or lopsided datasets. The weighted
    log-likelihood is tracked every eval_every iterations and the best
    parameter state seen is returned (momentum can overshoot).
    """
    if not matches:
        raise ValueError("fit_model requires at least one match")
    latest = max(m.date for m in matches)
    weights = [math.exp(-decay * (latest - m.date).days) for m in matches]

    teams = sorted({m.home for m in matches} | {m.away for m in matches})
    n = len(teams)
    log_alpha = {t: 0.0 for t in teams}
    log_beta = {t: 0.0 for t in teams}
    log_gamma = math.log(1.25)  # home teams score ~25% more than away
    log_base_rate = math.log(1.3)
    rho = 0.05

    # momentum buffers
    va = {t: 0.0 for t in teams}
    vb = {t: 0.0 for t in teams}
    vg = 0.0
    vmu = 0.0
    vr = 0.0

    def clip(v: float) -> float:
        return max(-clip_grad, min(clip_grad, v))

    def weighted_ll() -> float:
        total = 0.0
        for w, m in zip(weights, matches, strict=True):
            if m.home not in teams or m.away not in teams:
                continue
            base_rate_v = math.exp(log_base_rate)
            lambda_h = base_rate_v * math.exp(log_alpha[m.home] + log_beta[m.away] + log_gamma)
            lambda_a = base_rate_v * math.exp(log_alpha[m.away] + log_beta[m.home])
            x, y = m.home_goals, m.away_goals
            total += w * (
                math.log(max(tau_adjust(lambda_h, lambda_a, x, y, rho), 1e-300))
                + _pois_logpmf(x, lambda_h)
                + _pois_logpmf(y, lambda_a)
            )
        return total

    best_ll = -math.inf
    best_state: tuple[dict[str, float], dict[str, float], float, float, float] | None = None

    def snapshot() -> None:
        nonlocal best_ll, best_state
        ll = weighted_ll()
        if ll > best_ll:
            best_ll = ll
            best_state = (dict(log_alpha), dict(log_beta), log_gamma, log_base_rate, rho)

    for it in range(max_iter):
        ga = {t: 0.0 for t in teams}
        gb = {t: 0.0 for t in teams}
        gg = 0.0
        gmu = 0.0
        gr = 0.0

        for w, m in zip(weights, matches, strict=True):
            if m.home not in teams or m.away not in teams:
                continue
            base_rate = math.exp(log_base_rate)
            a_h, a_a = math.exp(log_alpha[m.home]), math.exp(log_alpha[m.away])
            b_h, b_a = math.exp(log_beta[m.home]), math.exp(log_beta[m.away])
            g = math.exp(log_gamma)
            lambda_h = base_rate * a_h * b_a * g
            lambda_a = base_rate * a_a * b_h
            x, y = m.home_goals, m.away_goals

            dtau_lh, dtau_la, dtau_rho = _tau_log_grads(lambda_h, lambda_a, x, y, rho)
            dll_lh = dtau_lh + x / max(lambda_h, eps) - 1.0
            dll_la = dtau_la + y / max(lambda_a, eps) - 1.0

            # d lambda / d log param = lambda for every multiplicative factor
            ga[m.home] += w * dll_lh * lambda_h
            gb[m.away] += w * dll_lh * lambda_h
            ga[m.away] += w * dll_la * lambda_a
            gb[m.home] += w * dll_la * lambda_a
            gg += w * dll_lh * lambda_h
            gmu += w * (dll_lh * lambda_h + dll_la * lambda_a)
            gr += w * dtau_rho

        for t in teams:
            va[t] = momentum * va[t] + (1 - momentum) * clip(ga[t])
            vb[t] = momentum * vb[t] + (1 - momentum) * clip(gb[t])
            log_alpha[t] = max(-param_clip, min(param_clip, log_alpha[t] + lr * va[t]))
            log_beta[t] = max(-param_clip, min(param_clip, log_beta[t] + lr * vb[t]))
        vg = momentum * vg + (1 - momentum) * clip(gg)
        vmu = momentum * vmu + (1 - momentum) * clip(gmu)
        vr = momentum * vr + (1 - momentum) * clip(gr)
        log_gamma = max(-param_clip, min(param_clip, log_gamma + lr * vg))
        log_base_rate = max(-param_clip, min(param_clip, log_base_rate + lr * vmu))
        rho += lr * vr
        rho = max(-0.5, min(0.5, rho))  # keep tau positive-ish

        # identifiability: mean log alpha = mean log beta = 0
        mean_a = sum(log_alpha.values()) / n
        mean_b = sum(log_beta.values()) / n
        for t in teams:
            log_alpha[t] -= mean_a
            log_beta[t] -= mean_b

        if it % eval_every == 0:
            snapshot()

    if best_state is not None:
        log_alpha, log_beta, log_gamma, log_base_rate, rho = best_state

    attack = {t: math.exp(log_alpha[t]) for t in teams}
    defense = {t: math.exp(log_beta[t]) for t in teams}
    base_rate = math.exp(log_base_rate)
    # arithmetic-mean normalization so base_rate = league avg goals per team
    mean_a = sum(attack.values()) / n
    mean_b = sum(defense.values()) / n
    attack = {t: a / mean_a for t, a in attack.items()}
    defense = {t: b / mean_b for t, b in defense.items()}
    base_rate *= mean_a * mean_b

    return TeamModel(
        attack=attack,
        defense=defense,
        gamma=math.exp(log_gamma),
        rho=rho,
        base_rate=base_rate,
        fitted_date=latest,
    )


def score_matrix(model: TeamModel, home: str, away: str) -> list[ScoreProb]:
    """Full score probability matrix (capped at MAX_GOALS per team)."""
    a_h = model.attack.get(home, 1.0)
    a_a = model.attack.get(away, 1.0)
    b_h = model.defense.get(home, 1.0)
    b_a = model.defense.get(away, 1.0)
    lambda_h = model.base_rate * a_h * b_a * model.gamma
    lambda_a = model.base_rate * a_a * b_h

    home_pmf = [math.exp(_pois_logpmf(k, lambda_h)) for k in range(MAX_GOALS + 1)]
    away_pmf = [math.exp(_pois_logpmf(k, lambda_a)) for k in range(MAX_GOALS + 1)]

    out: list[ScoreProb] = []
    for x in range(MAX_GOALS + 1):
        for y in range(MAX_GOALS + 1):
            p = tau_adjust(lambda_h, lambda_a, x, y, model.rho) * home_pmf[x] * away_pmf[y]
            out.append(ScoreProb(home_goals=x, away_goals=y, prob=max(p, 0.0)))
    return out


def totals_distribution(model: TeamModel, home: str, away: str) -> list[float]:
    """P(total_goals == k) for k in 0..2*MAX_GOALS."""
    probs = score_matrix(model, home, away)
    dist = [0.0] * (2 * MAX_GOALS + 1)
    for sp in probs:
        dist[sp.home_goals + sp.away_goals] += sp.prob
    total = sum(dist)
    if total > 0:
        dist = [p / total for p in dist]
    return dist


def p_over(model: TeamModel, home: str, away: str, line: float) -> float:
    """Model probability that total goals exceed `line` (e.g. 2.5)."""
    dist = totals_distribution(model, home, away)
    over = 0.0
    for k, p in enumerate(dist):
        if k > line:
            over += p
    return over


def p_under(model: TeamModel, home: str, away: str, line: float) -> float:
    return 1.0 - p_over(model, home, away, line)


def expected_total(model: TeamModel, home: str, away: str) -> float:
    """Model fair total (expected sum of goals)."""
    dist = totals_distribution(model, home, away)
    return sum(k * p for k, p in enumerate(dist))
