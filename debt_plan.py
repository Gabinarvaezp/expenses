#!/usr/bin/env python3
"""Jorgie's debt payoff plan.

Usage:
  python3 debt_plan.py expenses.json debts.json [TODAY=YYYY-MM-DD] --savings savings.json [--email OUTDIR --who Jorgie|Gabby]

Plans for three owners: Jorgie, Gabby and Together (Cozy House). accounts and goals carry "owner".
goals: [{id "gl01", owner, name, kind (Purchase/Home), target (USD), by_month ("" or YYYY-MM), saved (USD),
         uses_cozy_fund (true for the shared house: the Cozy House fund counts as saved), raw_line, origin}]

Reads Jorgie's paychecks (expenses with person "Jorgie", type "Income", item containing
"Target" or "Valet"), his everyday + recurring spending, and his debts (debts.json), then
writes the computed plan into debts.json["plan"]. With --email it also writes OUTDIR/plan.html
(the email body) and OUTDIR/plan.txt (plain-text version).

debts.json:
{
  "settings": {"goal_month": "2027-04", "target_checks_per_month": 2.17,
               "valet_checks_per_month": 4.33, "cushion_pct": 10},
  "accounts": [{"id": "d01", "name": "Watch", "kind": "Watch", "balance": 2800, "apr": 0,
                "monthly": 0, "paid_from": "Valet", "added": "2026-11",
                "last_payment_id_at_set": "", "raw_line": "Debt watch 2800", "origin": "note"}],
  "payments": [{"id": "p001", "month": "2026-11", "debt_id": "d01", "amount": 300,
                "raw_line": "Paid watch 300", "origin": "note"}],
  "plan_requests": [{"id": "r001", "month": "2026-11", "raw_line": "send plan", "sent": "2026-11-10"}],
  "plan": {... written by this script ...}
}
- balance = the balance when it was written (or last updated); payments with an id greater than
  last_payment_id_at_set are subtracted from it.
- apr = yearly interest % (0 if unknown/none); monthly = required monthly payment or minimum (0 if none).
- paid_from = "Valet" (the watch) or "Target" (everything else).
Free money: whatever is left over in a finished month (income logged that month minus recurring + everyday
spending, the Cozy House saving, personal pots and debt payments) rolls into a personal "Free money" pot.
Expenses with "from_free": true are paid out of it (they do not count against that month).
Money from the Cozy House savings and Jorgie's automatic USD 1,300 are never used.
Paychecks should be what lands in his account (after the automatic saving).
"""
import html, json, sys
from datetime import date

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
DEFAULTS = {'goal_month': '2027-04', 'target_checks_per_month': 2.17, 'valet_checks_per_month': 4.33, 'cushion_pct': 20}


def mname(m, short=False):
    y, mm = map(int, m.split('-'))
    return (MONTHS[mm - 1][:3] if short else MONTHS[mm - 1]) + ' ' + str(y)


def add_month(m, k=1):
    y, mm = map(int, m.split('-'))
    mm += k
    while mm > 12: mm -= 12; y += 1
    while mm < 1: mm += 12; y -= 1
    return f'{y}-{mm:02d}'


def months_between(a, b):
    ya, ma = map(int, a.split('-')); yb, mb = map(int, b.split('-'))
    return (yb - ya) * 12 + (mb - ma)


def usd(v):
    return ('-$' if v < 0 else '$') + f'{abs(v):,.2f}'


def usd0(v):
    return ('-$' if v < 0 else '$') + f'{abs(round(v)):,.0f}'


def current_balance(acc, payments):
    cut = acc.get('last_payment_id_at_set') or ''
    paid = sum(p['amount'] for p in payments if p['debt_id'] == acc['id'] and p['id'] > cut)
    return max(0.0, round(float(acc['balance']) - paid, 2))


def job_of(item):
    s = item.lower()
    if 'valet' in s: return 'Valet'
    if 'target' in s: return 'Target'
    return None


def compute(expenses, debts, today, owner='Jorgie'):
    st = dict(DEFAULTS); st.update(debts.get('settings') or {})
    cur = today.strftime('%Y-%m')
    goal = st['goal_month']
    accounts = [a for a in debts.get('accounts', []) if not a.get('closed') and a.get('owner', 'Jorgie') == owner]
    payments = debts.get('payments', [])
    # paychecks and spending are only known for Jorgie (Target/Valet); Gabby and Together plan on the monthly amount needed
    j = [e for e in expenses if e['person'] == 'Jorgie'] if owner == 'Jorgie' else []

    # --- income per job: average of the last 6 checks x checks per month
    income = {}
    for job, key in (('Target', 'target_checks_per_month'), ('Valet', 'valet_checks_per_month')):
        checks = [e['amount_usd'] for e in j if e['type'] == 'Income' and job_of(e['item']) == job][-6:]
        avg = round(sum(checks) / len(checks), 2) if checks else 0.0
        income[job] = {'per_check': avg, 'checks_per_month': st[key], 'monthly': round(avg * st[key], 2), 'n_logged': len(checks)}
    extra_income = [e for e in j if e['type'] == 'Income' and not job_of(e['item']) and e['month'] == cur]

    # --- his own monthly spending (everyday + recurring), average of up to the last 3 months that have data
    by_m = {}
    for e in j:
        if e['type'] in ('Variable', 'Fixed'): by_m[e['month']] = by_m.get(e['month'], 0) + e['amount_usd']
    past = sorted(m for m in by_m if m < cur)[-3:]
    if past: spend = round(sum(by_m[m] for m in past) / len(past), 2)
    elif cur in by_m:  # first month: project from the days so far (at least 15 days, so one early batch does not explode)
        spend = round(by_m[cur] / max(today.day, 15) * 30.4, 2)
    else: spend = 0.0

    cushion = st['cushion_pct'] / 100
    target_free = max(0.0, (income['Target']['monthly'] - spend) * (1 - cushion))
    valet_free = income['Valet']['monthly']
    extra_now = sum(e['amount_usd'] for e in extra_income)

    debts_now = []
    for a in accounts:
        b = current_balance(a, payments)
        orig = float(a.get('original', a['balance']))
        promo = a.get('interest_free_until') or ''
        need = float(a.get('monthly') or 0)
        if promo and b > 0:  # 0% deal: must be fully paid by the end of that month
            need = max(need, -(-b // max(1, months_between(cur, promo) + 1)))
        mg = max(1, months_between(cur, goal) + 1)
        # monthly payment that finishes this debt by the goal month (long loans like a car keep their own monthly payment)
        long_loan = a.get('kind') in ('Car', 'Loan', 'Mortgage') and float(a.get('monthly') or 0) > 0
        r = float(a.get('apr') or 0) / 1200
        by_goal = -(-((b * r / (1 - (1 + r) ** -mg)) if r else b / mg) // 1)  # equal payments incl. interest, rounded up to the dollar
        goal_m = (max(need, float(a['monthly'])) if long_loan else max(need, by_goal)) if b > 0 else 0
        debts_now.append({'id': a['id'], 'name': a['name'], 'kind': a.get('kind', 'Other'), 'apr': float(a.get('apr') or 0),
                          'monthly': float(a.get('monthly') or 0), 'needed_monthly': round(need, 2), 'goal_monthly': round(goal_m, 2),
                          'interest_free_until': promo,
                          'paid_from': a.get('paid_from', 'Target'),
                          'balance': b, 'original': max(orig, b),
                          'paid_so_far': round(sum(p['amount'] for p in payments if p['debt_id'] == a['id']), 2)})

    # a job with no paycheck logged yet: assume it covers just the minimum of its own debts (estimated plan)
    estimated = income['Target']['n_logged'] == 0 or income['Valet']['n_logged'] == 0
    if income['Valet']['n_logged'] == 0:
        valet_free = sum(d['goal_monthly'] for d in debts_now if d['paid_from'] == 'Valet' and d['balance'] > 0)
    if income['Target']['n_logged'] == 0:
        target_free = sum(d['goal_monthly'] for d in debts_now if d['paid_from'] != 'Valet' and d['balance'] > 0)
    # until a full month of his spending is logged, only use up to half of the Target pay (living costs are not known yet)
    half_rule = bool(income['Target']['n_logged']) and not past
    if half_rule:
        target_free = min(target_free, income['Target']['monthly'] * 0.5)

    # --- month-by-month simulation
    bal = {d['id']: d['balance'] for d in debts_now}
    info = {d['id']: d for d in debts_now}
    order_extra = lambda ids: sorted(ids, key=lambda i: (-info[i]['apr'], bal[i]))
    timeline, payoff, shortfall, first, first_t = [], {}, False, None, {}
    interest_total = 0.0
    m = cur
    for step in range(72):
        if all(bal[i] <= 0.005 for i in bal): break
        pays = {i: 0.0 for i in bal}
        src_t = {i: 0.0 for i in bal}  # part paid with Target money (the rest is Valet money)
        for i in bal:  # interest
            if bal[i] > 0 and info[i]['apr']:
                it = bal[i] * info[i]['apr'] / 1200; bal[i] += it; interest_total += it
        tpool, vpool = target_free, valet_free
        if step == 0: vpool += extra_now  # extra money this month (gifts, bonuses) helps the Valet debt first
        # 1) Valet debts (the watch) get all Valet money
        for i in sorted([i for i in bal if info[i]['paid_from'] == 'Valet' and bal[i] > 0], key=lambda i: bal[i]):
            p = min(bal[i], vpool); pays[i] += p; bal[i] -= p; vpool -= p
        # 2) minimums / monthly payments on Target debts
        for i in [i for i in bal if info[i]['paid_from'] != 'Valet' and bal[i] > 0]:
            need = min(bal[i], info[i]['needed_monthly'])
            p = min(need, tpool); pays[i] += p; src_t[i] += p; bal[i] -= p; tpool -= p
            if p + 0.005 < need: shortfall = True
        # 2b) a Valet debt that did not get its minimum this month is topped up from Target money
        for i in [i for i in bal if info[i]['paid_from'] == 'Valet' and bal[i] > 0]:
            short = min(bal[i], info[i]['needed_monthly']) - pays[i]
            if short > 0.005:
                p = min(short, tpool); pays[i] += p; src_t[i] += p; bal[i] -= p; tpool -= p
                if p + 0.005 < short: shortfall = True
        # 3) everything left goes to the next debt (highest interest first, then smallest)
        #    (Target money only helps Valet debts with their minimum, never with extra: Valet pays the watch)
        for i in order_extra([i for i in bal if bal[i] > 0]):
            pv = min(bal[i], vpool); pays[i] += pv; bal[i] -= pv; vpool -= pv
            if info[i]['paid_from'] != 'Valet' or st.get('target_helps_valet'):
                pt = min(bal[i], tpool); pays[i] += pt; src_t[i] += pt; bal[i] -= pt; tpool -= pt
        for i in bal:
            if bal[i] <= 0.005 and i not in payoff and (pays[i] > 0 or info[i]['balance'] == 0): payoff[i] = m
        timeline.append({'month': m, 'payments': {i: round(v, 2) for i, v in pays.items() if v > 0}, 'by_debt': {i: round(max(0, v), 2) for i, v in bal.items()},
                         'left': round(sum(max(0, v) for v in bal.values()), 2)})
        if first is None: first = {i: round(v, 2) for i, v in pays.items()}; first_t = dict(src_t)
        m = add_month(m)
    for d in debts_now:
        if d['balance'] <= 0: payoff[d['id']] = payoff.get(d['id'], cur)
    debt_free = max(payoff.values()) if payoff and len(payoff) == len(bal) else None
    left_at_goal = next((t['left'] for t in timeline if t['month'] == goal), 0.0 if (debt_free and debt_free <= goal) else (timeline[-1]['left'] if timeline else 0.0))

    # --- per paycheck instructions (from the first month of the plan)
    first = first or {}
    per_check = {'Target': [], 'Valet': []}
    for d in debts_now:
        amt = first.get(d['id'], 0)
        if amt <= 0: continue
        t_part = first_t.get(d['id'], 0); v_part = amt - t_part
        for src, part in (('Valet', v_part), ('Target', t_part)):
            if part > 0.5 and income[src]['n_logged']:  # only when we know his checks for that job
                per_check[src].append({'debt': d['name'], 'amount': round(part / (income[src]['checks_per_month'] or 1), 2)})
    for d in debts_now:
        d['payoff_month'] = payoff.get(d['id'])
        n_src = income['Valet' if d['paid_from'] == 'Valet' else 'Target']['checks_per_month'] or 1
        d['per_check'] = round(first.get(d['id'], 0) / n_src, 2) if income['Valet' if d['paid_from'] == 'Valet' else 'Target']['n_logged'] else None
        d['this_month'] = round(first.get(d['id'], 0), 2)
        d['by_goal'] = bool(d['payoff_month'] and d['payoff_month'] <= goal)
        d['pct_paid'] = round((1 - d['balance'] / d['original']) * 100, 1) if d['original'] else 100.0
        d['late_for_promo'] = bool(d['interest_free_until'] and d['balance'] > 0 and (not d['payoff_month'] or d['payoff_month'] > d['interest_free_until']))

    total = round(sum(d['balance'] for d in debts_now), 2)
    months_left = max(1, months_between(cur, goal) + 1)
    steps = make_steps(debts_now, income, per_check, spend, goal, debt_free, left_at_goal, shortfall, estimated, half_rule)
    return {
        'generated': today.isoformat(), 'month': cur, 'goal_month': goal, 'months_to_goal': months_left,
        'total_debt': total, 'debt_free_month': debt_free, 'left_at_goal': round(left_at_goal, 2),
        'income': income, 'monthly_spending': spend, 'cushion_pct': st['cushion_pct'],
        'available_monthly': round(sum(first.values()) if first else 0, 2), 'target_free': round(target_free, 2), 'valet_free': round(valet_free, 2),
        'extra_this_month': round(extra_now, 2), 'interest_estimate': round(interest_total, 2),
        'shortfall': shortfall, 'debts': debts_now, 'per_check': per_check, 'steps': steps,
        'timeline': [{'month': t['month'], 'left': t['left'], 'paid': round(sum(t['payments'].values()), 2), 'by_debt': t['by_debt'], 'pay_by_debt': t['payments']} for t in timeline[:24]],
        'estimated': estimated,
        'ready': bool(debts_now) and (income['Target']['n_logged'] + income['Valet']['n_logged']) > 0,
    }


def make_steps(debts, income, per_check, spend, goal, debt_free, left_at_goal, shortfall, estimated=False, half_rule=False):
    """Very short lines (the app shows numbers; these are only for the email)."""
    if not debts:
        return ['Write what you owe in your note (e.g. "Reloj 2890").']
    s = []
    for d in sorted([d for d in debts if d['balance'] > 0 and d['payoff_month']], key=lambda d: d['payoff_month']):
        s.append(f"{d['name']} paid off: {mname(d['payoff_month'], True)}")
    for d in debts:
        if d.get('late_for_promo'):
            s.append(f"Pay the {d['name']} first: 0% ends {mname(d['interest_free_until'], True)}")
    if shortfall:
        s.append('Money is short for the monthly payments')
    return s


# ---------------- goals (things to buy, the house) ----------------
def latest_rate(expenses, savings):
    rs = [e.get('rate') for e in expenses + savings.get('entries', []) if e.get('rate') and e.get('rate') > 100]
    return rs[-1] if rs else 4000.0


def fund_outlook(savings, rate, cur, goal):
    """The Cozy House fund: balance now, money going in each month, and where it will be."""
    entries = savings.get('entries', [])
    bal = round(sum(float(e.get('amount_usd') or 0) for e in entries), 2)
    monthly = 0.0
    for pl in savings.get('plan', []):
        monthly += float(pl['monthly']) / rate if pl.get('currency') == 'COP' else float(pl['monthly'])
    monthly = round(monthly, 2)
    proj = [{'month': add_month(cur, k), 'balance': round(bal + monthly * (k + 1), 2)} for k in range(18)]
    at_goal = next((x['balance'] for x in proj if x['month'] == goal), bal)
    return {'balance': bal, 'monthly_in': monthly, 'at_goal': at_goal, 'projection': proj}


def compute_goals(debts, owner, cur, fund):
    out = []
    for g in debts.get('goals', []):
        if g.get('owner', 'Jorgie') != owner or g.get('closed'):
            continue
        target = float(g['target'])
        uses_fund = bool(g.get('uses_cozy_fund'))
        saved = fund['balance'] if (uses_fund and fund) else float(g.get('saved') or 0)
        remaining = max(0.0, round(target - saved, 2))
        by = g.get('by_month') or ''
        item = {'id': g['id'], 'name': g['name'], 'kind': g.get('kind', 'Purchase'), 'target': round(target, 2), 'saved': round(saved, 2),
                'remaining': remaining, 'pct': round(min(100.0, saved / target * 100), 1) if target else 100.0,
                'by_month': by, 'uses_cozy_fund': uses_fund, 'monthly_needed': None, 'reach_month': None, 'options': []}
        if remaining <= 0:
            item['reach_month'] = cur
        elif by:
            n = max(1, months_between(cur, by) + 1)
            item['monthly_needed'] = round(remaining / n, 2)
            item['reach_month'] = by
        if uses_fund and fund and fund['monthly_in'] > 0 and remaining > 0:
            k = -(-remaining // fund['monthly_in'])
            item['fund_reach_month'] = add_month(cur, int(k) - 1)
            if not by:
                item['monthly_needed'] = fund['monthly_in']
                item['reach_month'] = item['fund_reach_month']
        if remaining > 0:
            item['options'] = [{'months': n, 'monthly': round(remaining / n, 2), 'month': add_month(cur, n - 1)} for n in (3, 6, 12, 24)]
            if not item['monthly_needed']:
                item['monthly_needed'] = item['options'][1]['monthly']
                item['reach_month'] = item['options'][1]['month']
                item['suggested'] = True
        out.append(item)
    return out


def pot_monthly_at(pt, m):
    """A pot's monthly amount in month m. pt["changes"] = [{"month": "YYYY-MM", "from": old, "to": new}, ...]
    (the new amount applies from that month on); without changes it is always pt["monthly"]."""
    ch = sorted(pt.get('changes') or [], key=lambda c: c['month'])
    if not ch:
        return float(pt['monthly'])
    v = float(ch[0].get('from', pt['monthly']))
    for c in ch:
        if c['month'] <= m: v = float(c['to'])
    return v


def compute_pots(debts, who, cur, rate):
    """Personal savings pots (money set aside automatically every month, e.g. a gifts fund)."""
    out = []
    for pt in debts.get('pots', []):
        if pt.get('person') != who:
            continue
        end = pt.get('end_month') or cur
        n = max(0, months_between(pt['start_month'], min(end, cur)) + 1) if pt['start_month'] <= cur else 0
        native = sum(pot_monthly_at(pt, add_month(pt['start_month'], k)) for k in range(n)) + float(pt.get('adjust') or 0)
        cop = pt.get('currency') == 'COP'
        to_usd = (lambda v: v / rate) if cop else (lambda v: v)
        out.append({'id': pt['id'], 'name': pt['name'], 'active': pt.get('active', True), 'start_month': pt['start_month'],
                    'monthly': round(to_usd(float(pt['monthly'])), 2), 'monthly_cop': round(float(pt['monthly'])) if cop else None,
                    'saved': round(to_usd(native), 2), 'saved_cop': round(native) if cop else None, 'months': n})
    return out


def compute_free(expenses, savings, debts, who, cur, rate):
    """Free money: what was left over in each finished month (income logged that month minus
    recurring + everyday spending, the Cozy House saving, personal pots and debt payments).
    It rolls into a personal pot for trips and fun. Expenses marked "from_free" are paid out of it."""
    mine = [e for e in expenses if e['person'] == who]
    inc, fix, var, spent_free = {}, {}, {}, {}
    for e in mine:
        m, v = e['month'], float(e['amount_usd'])
        if e['type'] == 'Income': inc[m] = inc.get(m, 0) + v
        elif e.get('from_free'): spent_free[m] = spent_free.get(m, 0) + v
        elif e['type'] == 'Fixed': fix[m] = fix.get(m, 0) + v
        else: var[m] = var.get(m, 0) + v
    sav = {}
    if who == 'Gabby':  # Jorgie's paychecks already arrive after his automatic saving
        for x in savings.get('entries', []):
            if x['person'] == who and x.get('kind') in ('Monthly saving', 'Extra saving'):
                sav[x['month']] = sav.get(x['month'], 0) + float(x.get('amount_usd') or 0)
    def pots_in(m):
        t = 0.0
        for pt in debts.get('pots', []):
            if pt.get('person') == who and pt['start_month'] <= m and (not pt.get('end_month') or m <= pt['end_month']):
                v = pot_monthly_at(pt, m); t += v / rate if pt.get('currency') == 'COP' else v
        return t
    mine_debts = {a['id'] for a in debts.get('accounts', []) if a.get('owner', 'Jorgie') == who}
    pay = {}
    for x in debts.get('payments', []):
        if x['debt_id'] in mine_debts: pay[x['month']] = pay.get(x['month'], 0) + float(x['amount'])
    def month_row(m):
        out = fix.get(m, 0) + var.get(m, 0) + sav.get(m, 0) + pots_in(m) + pay.get(m, 0)
        return {'month': m, 'income': round(inc[m], 2), 'fixed': round(fix.get(m, 0), 2), 'variable': round(var.get(m, 0), 2),
                'saved': round(sav.get(m, 0) + pots_in(m), 2), 'debts': round(pay.get(m, 0), 2), 'left': round(inc[m] - out, 2)}
    months = [month_row(m) for m in sorted(inc) if m < cur]
    added = round(sum(max(0.0, x['left']) for x in months), 2)
    spent = round(sum(spent_free.values()), 2)
    now = month_row(cur) if cur in inc else None
    to_cop = (lambda v: round(v * rate)) if who == 'Gabby' else (lambda v: None)
    return {'months': months, 'added': added, 'spent': spent, 'balance': round(added - spent, 2), 'balance_cop': to_cop(added - spent),
            'this_month': now, 'spent_items': [{'month': e['month'], 'item': e['item'], 'amount': e['amount_usd']} for e in mine if e.get('from_free')]}


def free_tip(free, debts_list, rate=None):
    """Suggest how to use free money: half to the costliest debt (interest first, then the 0% that ends soonest),
    the other half stays free for trips and fun. No debts → no suggestion."""
    bal = free.get('balance') or 0
    live = [d for d in debts_list if d.get('balance', 0) > 0]
    if bal < 20 or not live:
        return None
    d = sorted(live, key=lambda d: (-(d.get('apr') or 0), d.get('interest_free_until') or '9999', -d['balance']))[0]
    amt = min(d['balance'], round(bal / 2 / 10) * 10 or round(bal / 2))
    mon = d.get('this_month') or d.get('goal_monthly') or 0
    sooner = 0
    if mon > 0:
        sooner = int(-(-d['balance'] // mon) - -(-max(0.0, d['balance'] - amt) // mon))
    clears = amt >= d['balance'] - 0.01
    cop_amt = (d.get('balance_cop') if clears and d.get('balance_cop') else round(amt * rate / 1000) * 1000) if rate else None
    return {'debt': d['name'], 'amount': round(amt, 2), 'amount_cop': cop_amt, 'months_sooner': sooner,
            'keep': round(bal - amt, 2), 'clears': clears, 'reason': 'interest' if (d.get('apr') or 0) > 0 else 'payoff'}


def budget(expenses, savings, who, cur, rate, debts_monthly, goals_monthly, pots_monthly=0.0):
    """Money in vs out for one person: income = average of the last 3 months they logged income."""
    mine = [e for e in expenses if e['person'] == who]
    inc_m, inc_c, fx_m, vr_m = {}, {}, {}, {}
    for e in mine:
        if e['type'] == 'Income':
            inc_m[e['month']] = inc_m.get(e['month'], 0) + float(e['amount_usd'])
            inc_c[e['month']] = inc_c.get(e['month'], 0) + float(e.get('amount_cop') or 0)
        elif e.get('from_free'): continue  # paid out of free money, not the monthly budget
        elif e['type'] == 'Fixed': fx_m[e['month']] = fx_m.get(e['month'], 0) + float(e['amount_usd'])
        else: vr_m[e['month']] = vr_m.get(e['month'], 0) + float(e['amount_usd'])
    months = sorted(inc_m)[-3:]
    if not months:
        return None
    income = sum(inc_m[m] for m in months) / len(months)
    def avg(d):
        past = sorted(m for m in d if m < cur)[-3:]
        return sum(d[m] for m in past) / len(past) if past else d.get(cur, 0)
    fixed, variable = avg(fx_m), avg(vr_m)
    spend = fixed + variable
    sav = 0.0
    if who == 'Gabby':  # Jorgie's saving leaves his pay before it reaches him; Gabby's comes out of her income
        for pl in savings.get('plan', []):
            if pl['person'] == 'Gabby':
                sav = float(pl['monthly']) / rate if pl.get('currency') == 'COP' else float(pl['monthly'])
    free = income - spend - sav - pots_monthly - debts_monthly - goals_monthly
    return {'income_avg': round(income, 2), 'income_avg_cop': round(sum(inc_c[m] for m in months) / len(months)) if who == 'Gabby' else None, 'months_used': months,
            'spend_avg': round(spend, 2), 'fixed_avg': round(fixed, 2), 'variable_avg': round(variable, 2), 'savings_monthly': round(sav, 2), 'pots_monthly': round(pots_monthly, 2), 'debts_monthly': round(debts_monthly, 2),
            'goals_monthly': round(goals_monthly, 2), 'free': round(free, 2)}


def compute_all(expenses, debts, savings, today):
    cur = today.strftime('%Y-%m')
    st = dict(DEFAULTS); st.update(debts.get('settings') or {})
    rate = latest_rate(expenses, savings)
    fund = fund_outlook(savings, rate, cur, st['goal_month'])
    people = {}
    for who in ('Jorgie', 'Gabby', 'Together'):
        p = compute(expenses, debts, today, who)
        p['goals'] = compute_goals(debts, who, cur, fund)
        p['goals_monthly'] = round(sum(g['monthly_needed'] or 0 for g in p['goals'] if g['remaining'] > 0 and not g['uses_cozy_fund']), 2)
        if who == 'Together':
            p['fund'] = fund
        else:
            p['pots'] = compute_pots(debts, who, cur, rate)
            p['pots_monthly'] = round(sum(x['monthly'] for x in p['pots'] if x['active']), 2)
            p['free'] = compute_free(expenses, savings, debts, who, cur, rate)
            p['free']['tip'] = free_tip(p['free'], p['debts'], rate if who == 'Gabby' else None)
            p['budget'] = budget(expenses, savings, who, cur, rate, p['available_monthly'] if p['debts'] else 0, p['goals_monthly'], p['pots_monthly'])
        people[who] = p
    return {'generated': today.isoformat(), 'month': cur, 'goal_month': st['goal_month'], 'rate': rate, 'people': people}


# ---------------- email ----------------
TEXT, MUTED, LINE, ACCENT, GOOD = '#2F3542', '#8A919C', '#E3E6EA', '#9B59D0', '#2E9E6A'


def email_html(plan, who, url):
    e = html.escape
    p, t = plan['people'][who], plan['people']['Together']
    if who == 'Together': p = {'debts': [], 'goals': [], 'per_check': {}}
    def card(title, body):
        return (f'<tr><td style="padding:0 0 14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="background:#fff;border:1px solid {LINE};border-radius:6px;"><tr><td style="padding:16px 18px;">'
                f'<div style="font-size:13px;font-weight:700;color:{TEXT};margin-bottom:10px;">{e(title)}</div>{body}</td></tr></table></td></tr>')
    kpi = lambda label, val, sub='': (f'<td width="33%" valign="top" style="padding:4px 6px;"><div style="font-size:11px;color:{MUTED};">{e(label)}</div>'
                                      f'<div style="font-size:20px;font-weight:700;color:{TEXT};">{e(val)}</div><div style="font-size:11px;color:{MUTED};">{e(sub)}</div></td>')
    bar = lambda pct: (f'<div style="height:6px;background:#EEF0F3;border-radius:3px;margin:6px 0 4px;"><div style="width:{max(0, min(100, pct))}%;height:6px;background:{ACCENT};border-radius:3px;"></div></div>')
    def row(name, sub, right, right_sub, pct):
        return (f'<tr><td style="padding:8px 0;border-bottom:1px solid #EEF0F3;"><div style="font-size:14px;font-weight:600;color:{TEXT};">{e(name)}</div>{bar(pct)}'
                f'<div style="font-size:11px;color:{MUTED};">{e(sub)}</div></td><td align="right" valign="top" style="padding:8px 0 8px 10px;border-bottom:1px solid #EEF0F3;'
                f'font-size:14px;font-weight:700;color:{TEXT};white-space:nowrap;">{e(right)}<div style="font-size:11px;font-weight:400;color:{MUTED};">{e(right_sub)}</div></td></tr>')
    tbl = lambda rows: f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
    def debts_rows(q):
        return ''.join(row(d['name'], ('Done ' + mname(d['payoff_month'], True)) if d['payoff_month'] else 'Long term', usd(d['balance']), usd0(d['this_month']) + ' a month', d['pct_paid'])
                       for d in sorted(q['debts'], key=lambda d: d['payoff_month'] or '9999'))
    def goals_rows(q):
        return ''.join(row(g['name'], ('Ready ' + mname(g['reach_month'], True)) if g['reach_month'] else '', usd0(g['target']),
                           (usd0(g['monthly_needed']) + ' a month') if g['monthly_needed'] else 'ready', g['pct']) for g in q['goals'])
    body = ''
    if p['debts']:
        df = mname(p['debt_free_month'], True) if p['debt_free_month'] else '—'
        body += card('Where you stand', '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                     + kpi('You owe', usd(p['total_debt'])) + kpi('Pay each month', usd0(p['available_monthly'])) + kpi('Debt-free', df) + '</tr></table>')
        checks = ''
        for job in ('Valet', 'Target'):
            rows = ''.join(f'<tr><td style="padding:5px 0;font-size:14px;color:{TEXT};">{e(x["debt"])}</td><td align="right" style="padding:5px 0;font-size:14px;font-weight:700;color:{TEXT};">{usd(x["amount"])}</td></tr>' for x in p['per_check'].get(job, []))
            if rows:
                checks += f'<div style="font-size:12px;font-weight:700;color:{ACCENT};margin:6px 0 2px;">EACH {job.upper()} CHECK</div>' + tbl(rows)
        if checks:
            body += card('Every paycheck', checks)
        body += card('Debts', tbl(debts_rows(p)))
    if p['goals']:
        body += card('Goals', tbl(goals_rows(p)))
    if p.get('pots'):
        body += card('Savings', tbl(''.join(row(x['name'], usd0(x['monthly']) + ' a month', usd0(x['saved']), 'saved', 100) for x in p['pots'])))
    fr = p.get('free') or {}
    if fr.get('months') or fr.get('spent'):
        rows = ''.join(row(mname(x['month']), 'left over', usd0(max(0, x['left'])), 'added' if x['left'] > 0 else 'nothing left', 100 if x['left'] > 0 else 0) for x in fr['months'])
        body += card('Free money · ' + usd0(fr['balance']), tbl(rows) + (f'<div style="font-size:11px;color:{MUTED};margin-top:6px;">{usd0(fr["spent"])} used so far</div>' if fr['spent'] else ''))
    bg = p.get('budget')
    if bg:
        body += card('Money in vs out', '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                     + kpi('Expected income', usd0(bg['income_avg']), 'avg of ' + str(len(bg['months_used'])) + ' mo')
                     + kpi('Fixed + variable', usd0(bg['fixed_avg']) + ' + ' + usd0(bg['variable_avg'])) + kpi('Left over', usd0(bg['free'])) + '</tr></table>')
    f = t.get('fund') or {}
    together = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                + kpi('Cozy House fund', usd0(f.get('balance', 0))) + kpi('Going in a month', usd0(f.get('monthly_in', 0)))
                + kpi('By ' + mname(plan['goal_month'], True), usd0(f.get('at_goal', 0))) + '</tr></table>')
    if t['goals']: together += tbl(goals_rows(t))
    if t['debts']: together += tbl(debts_rows(t))
    body += card('Together · Cozy House', together)
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#F1F2F4;font-family:Inter,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F2F4;"><tr><td align="center" style="padding:20px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
<tr><td style="padding:4px 0 16px;"><div style="font-size:22px;font-weight:700;color:{TEXT};">{'Our Plan' if who == 'Together' else 'Your Plan'}</div>
<div style="font-size:13px;color:{MUTED};">{e(who)} · {e(mname(plan["month"]))}</div></td></tr>
{body}
<tr><td style="padding:4px 0 20px;font-size:12px;"><a href="{e(url)}" style="color:{ACCENT};">Open the dashboard</a></td></tr>
</table></td></tr></table></body></html>"""


def email_text(plan, who, url):
    p, t = plan['people'][who], plan['people']['Together']
    if who == 'Together': p = {'debts': [], 'goals': [], 'per_check': {}}
    L = [f"Your Plan — {who} — {mname(plan['month'])}", '']
    if p['debts']:
        L += [f"You owe: {usd(p['total_debt'])} · pay {usd0(p['available_monthly'])} a month · debt-free {mname(p['debt_free_month'], True) if p['debt_free_month'] else '—'}"]
        for job in ('Valet', 'Target'):
            if p['per_check'].get(job):
                L.append(f'Each {job} check: ' + ', '.join(f"{usd(x['amount'])} to {x['debt']}" for x in p['per_check'][job]))
        L += [f"- {d['name']}: {usd(d['balance'])}, {usd0(d['this_month'])} a month" + (f", done {mname(d['payoff_month'], True)}" if d['payoff_month'] else '') for d in p['debts']]
    for g in p['goals'] + t['goals']:
        L.append(f"- Goal {g['name']}: {usd0(g['target'])}" + (f", {usd0(g['monthly_needed'])} a month" if g['monthly_needed'] else '') + (f", ready {mname(g['reach_month'], True)}" if g['reach_month'] else ''))
    f = t.get('fund') or {}
    L += ['', f"Cozy House fund: {usd0(f.get('balance', 0))} (+{usd0(f.get('monthly_in', 0))} a month)", '', f'Dashboard: {url}']
    return '\n'.join(L)


def main():
    args = [a for a in sys.argv[1:]]
    opt = {}
    for flag in ('--email', '--who', '--savings'):
        if flag in args:
            k = args.index(flag); opt[flag] = args[k + 1]; del args[k:k + 2]
    if len(args) < 2: sys.exit(__doc__)
    fe, fd = args[0], args[1]
    today = date.fromisoformat(args[2]) if len(args) > 2 else date.today()
    expenses = json.load(open(fe, encoding='utf-8'))
    debts = json.load(open(fd, encoding='utf-8'))
    savings = json.load(open(opt['--savings'], encoding='utf-8')) if '--savings' in opt else {'plan': [], 'entries': []}
    for k in ('accounts', 'payments', 'plan_requests', 'goals'): debts.setdefault(k, [])
    debts.setdefault('settings', dict(DEFAULTS))
    plan = compute_all(expenses, debts, savings, today)
    debts['plan'] = plan
    json.dump(debts, open(fd, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if '--email' in opt:
        import os
        who = opt.get('--who', 'Jorgie')
        os.makedirs(opt['--email'], exist_ok=True)
        url = 'https://gabinarvaezp.github.io/expenses/'
        open(os.path.join(opt['--email'], 'plan.html'), 'w', encoding='utf-8').write(email_html(plan, who, url))
        open(os.path.join(opt['--email'], 'plan.txt'), 'w', encoding='utf-8').write(email_text(plan, who, url))
    print(json.dumps({w: {'debt': q['total_debt'], 'debt_free': q['debt_free_month'], 'goals': [(g['name'], g['monthly_needed'], g['reach_month']) for g in q['goals']]} for w, q in plan['people'].items()}, indent=1))


if __name__ == '__main__':
    main()
