#!/usr/bin/env python3
"""Jorgie's debt payoff plan.

Usage:
  python3 debt_plan.py expenses.json debts.json [TODAY=YYYY-MM-DD] [--email OUTDIR]

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
Money from the Cozy House savings and Jorgie's automatic USD 1,300 are never used.
Paychecks should be what lands in his account (after the automatic saving).
"""
import html, json, sys
from datetime import date

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
DEFAULTS = {'goal_month': '2027-04', 'target_checks_per_month': 2.17, 'valet_checks_per_month': 4.33, 'cushion_pct': 10}


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


def compute(expenses, debts, today):
    st = dict(DEFAULTS); st.update(debts.get('settings') or {})
    cur = today.strftime('%Y-%m')
    goal = st['goal_month']
    accounts = [a for a in debts.get('accounts', []) if not a.get('closed')]
    payments = debts.get('payments', [])
    j = [e for e in expenses if e['person'] == 'Jorgie']

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
        debts_now.append({'id': a['id'], 'name': a['name'], 'kind': a.get('kind', 'Other'), 'apr': float(a.get('apr') or 0),
                          'monthly': float(a.get('monthly') or 0), 'paid_from': a.get('paid_from', 'Target'),
                          'balance': b, 'original': max(orig, b),
                          'paid_so_far': round(sum(p['amount'] for p in payments if p['debt_id'] == a['id']), 2)})

    # --- month-by-month simulation
    bal = {d['id']: d['balance'] for d in debts_now}
    info = {d['id']: d for d in debts_now}
    order_extra = lambda ids: sorted(ids, key=lambda i: (-info[i]['apr'], bal[i]))
    timeline, payoff, shortfall, first = [], {}, False, None
    interest_total = 0.0
    m = cur
    for step in range(72):
        if all(bal[i] <= 0.005 for i in bal): break
        pays = {i: 0.0 for i in bal}
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
            need = min(bal[i], info[i]['monthly'])
            p = min(need, tpool); pays[i] += p; bal[i] -= p; tpool -= p
            if p + 0.005 < need: shortfall = True
        # 3) everything left goes to the next debt (highest interest first, then smallest)
        pool = tpool + vpool
        for i in order_extra([i for i in bal if bal[i] > 0]):
            p = min(bal[i], pool); pays[i] += p; bal[i] -= p; pool -= p
        for i in bal:
            if bal[i] <= 0.005 and i not in payoff and (pays[i] > 0 or info[i]['balance'] == 0): payoff[i] = m
        timeline.append({'month': m, 'payments': {i: round(v, 2) for i, v in pays.items() if v > 0},
                         'left': round(sum(max(0, v) for v in bal.values()), 2)})
        if first is None: first = {i: round(v, 2) for i, v in pays.items()}
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
        # Valet money covers Valet debts first; anything else in month 1 comes from Target (or Valet leftovers)
        src = 'Valet' if d['paid_from'] == 'Valet' else 'Target'
        n = income[src]['checks_per_month'] or 1
        per_check[src].append({'debt': d['name'], 'amount': round(amt / n, 2)})
    for d in debts_now:
        d['payoff_month'] = payoff.get(d['id'])
        d['this_month'] = round(first.get(d['id'], 0), 2)
        d['by_goal'] = bool(d['payoff_month'] and d['payoff_month'] <= goal)
        d['pct_paid'] = round((1 - d['balance'] / d['original']) * 100, 1) if d['original'] else 100.0

    total = round(sum(d['balance'] for d in debts_now), 2)
    months_left = max(1, months_between(cur, goal) + 1)
    steps = make_steps(debts_now, income, per_check, spend, goal, debt_free, left_at_goal, shortfall)
    return {
        'generated': today.isoformat(), 'month': cur, 'goal_month': goal, 'months_to_goal': months_left,
        'total_debt': total, 'debt_free_month': debt_free, 'left_at_goal': round(left_at_goal, 2),
        'income': income, 'monthly_spending': spend, 'cushion_pct': st['cushion_pct'],
        'available_monthly': round(target_free + valet_free, 2), 'target_free': round(target_free, 2), 'valet_free': round(valet_free, 2),
        'extra_this_month': round(extra_now, 2), 'interest_estimate': round(interest_total, 2),
        'shortfall': shortfall, 'debts': debts_now, 'per_check': per_check, 'steps': steps,
        'timeline': [{'month': t['month'], 'left': t['left'], 'paid': round(sum(t['payments'].values()), 2)} for t in timeline[:24]],
        'ready': bool(debts_now) and (income['Target']['n_logged'] + income['Valet']['n_logged']) > 0,
    }


def make_steps(debts, income, per_check, spend, goal, debt_free, left_at_goal, shortfall):
    s = []
    if not debts:
        return ['Write each debt in your note, e.g. "Debt watch 2800" or "Debt credit card 3200 min 120 24%".']
    if not (income['Target']['n_logged'] or income['Valet']['n_logged']):
        s.append('Log your paychecks with a + sign, e.g. "+ Target 1050" and "+ Valet 400", so the plan knows what you earn.')
    for job in ('Valet', 'Target'):
        if per_check[job]:
            parts = ', '.join(f"{usd0(x['amount'])} to {x['debt']}" for x in per_check[job])
            s.append(f'Every {job} check: send {parts} the same day you get paid.')
    vd = [d for d in debts if d['paid_from'] == 'Valet' and d['balance'] > 0]
    for d in vd:
        if d['payoff_month']:
            s.append(f"Valet money pays the {d['name']} first; it is done in {mname(d['payoff_month'])}. Then that same money moves to the next debt.")
    td = sorted([d for d in debts if d['paid_from'] != 'Valet' and d['balance'] > 0], key=lambda d: (-d['apr'], d['balance']))
    if td:
        s.append('Pay at least the monthly payment on ' + ', '.join(d['name'] for d in td) + '. Any extra goes to the ' + td[0]['name'] + ' first' + (' (highest interest).' if td[0]['apr'] else '.'))
    s.append('Extra money (gifts, bonuses, tips) goes straight to the next debt in line. Log it with a + sign.')
    s.append('Never use the Cozy House savings or the automatic $1,300 for debts.')
    if debt_free and debt_free <= goal:
        s.append(f'On this plan you are debt-free by {mname(debt_free)}, before the {mname(goal)} goal.')
    elif left_at_goal > 0:
        s.append(f'By {mname(goal)} about {usd0(left_at_goal)} would still be left (mostly long loans like the car). Keep the monthly payment going after that.')
    if shortfall:
        s.append('Heads-up: the Target money left after your spending does not fully cover the monthly payments. Trim spending or add Valet shifts.')
    return s


# ---------------- email ----------------
TEXT, MUTED, LINE, ACCENT, GOOD = '#2F3542', '#8A919C', '#E3E6EA', '#4B9FD5', '#2E9E6A'


def email_html(p, url):
    e = html.escape
    def card(title, body):
        return (f'<tr><td style="padding:0 0 14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="background:#fff;border:1px solid {LINE};border-radius:6px;"><tr><td style="padding:16px 18px;">'
                f'<div style="font-size:13px;font-weight:700;color:{TEXT};margin-bottom:10px;">{e(title)}</div>{body}</td></tr></table></td></tr>')
    kpi = lambda label, val, sub='': (f'<td width="33%" valign="top" style="padding:4px 6px;"><div style="font-size:11px;color:{MUTED};">{e(label)}</div>'
                                      f'<div style="font-size:20px;font-weight:700;color:{TEXT};">{e(val)}</div><div style="font-size:11px;color:{MUTED};">{e(sub)}</div></td>')
    df = mname(p['debt_free_month']) if p['debt_free_month'] else 'After 6 years'
    kpis = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            + kpi('Total debt', usd(p['total_debt']))
            + kpi('Debt-free', df, 'goal ' + mname(p['goal_month']))
            + kpi('Left by ' + mname(p['goal_month'], True), usd0(p['left_at_goal']))
            + '</tr></table>')
    checks = ''
    for job in ('Target', 'Valet'):
        rows = ''.join(f'<tr><td style="padding:6px 0;font-size:14px;color:{TEXT};">{e(x["debt"])}</td><td align="right" style="padding:6px 0;font-size:14px;font-weight:700;color:{TEXT};">{usd(x["amount"])}</td></tr>' for x in p['per_check'][job])
        if rows:
            inc = p['income'][job]
            checks += (f'<div style="font-size:12px;font-weight:700;color:{ACCENT};margin:6px 0 2px;">EACH {job.upper()} CHECK '
                       f'<span style="color:{MUTED};font-weight:400;">(about {usd0(inc["per_check"])})</span></div>'
                       f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>')
    if not checks:
        checks = f'<div style="font-size:13px;color:{MUTED};">Log your debts and paychecks in your note to get amounts per check.</div>'
    drows = ''
    for d in sorted(p['debts'], key=lambda d: (d['payoff_month'] or '9999')):
        pct = max(0, min(100, d['pct_paid']))
        when = mname(d['payoff_month']) if d['payoff_month'] else 'later'
        tag = (f'<span style="color:{GOOD};">by goal</span>' if d['by_goal'] else f'<span style="color:{MUTED};">after goal</span>') if d['balance'] > 0 else f'<span style="color:{GOOD};">paid off</span>'
        drows += (f'<tr><td style="padding:8px 0;border-bottom:1px solid #EEF0F3;"><div style="font-size:14px;font-weight:600;color:{TEXT};">{e(d["name"])}'
                  f' <span style="font-size:11px;font-weight:400;color:{MUTED};">· {e(d["paid_from"])}{(" · " + str(d["apr"]).rstrip("0").rstrip(".") + "% APR") if d["apr"] else ""}</span></div>'
                  f'<div style="height:6px;background:#EEF0F3;border-radius:3px;margin:6px 0 4px;"><div style="width:{pct}%;height:6px;background:{ACCENT};border-radius:3px;"></div></div>'
                  f'<div style="font-size:11px;color:{MUTED};">Paid off {e(when)} · {tag}</div></td>'
                  f'<td align="right" valign="top" style="padding:8px 0 8px 10px;border-bottom:1px solid #EEF0F3;font-size:14px;font-weight:700;color:{TEXT};white-space:nowrap;">{usd(d["balance"])}'
                  f'<div style="font-size:11px;font-weight:400;color:{MUTED};">{usd0(d["this_month"])} this month</div></td></tr>')
    debts_t = f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{drows}</table>' if drows else ''
    steps = ''.join(f'<tr><td valign="top" style="padding:5px 8px 5px 0;font-size:13px;font-weight:700;color:{ACCENT};">{i}</td><td style="padding:5px 0;font-size:14px;color:#474E5A;line-height:1.45;">{e(t)}</td></tr>' for i, t in enumerate(p['steps'], 1))
    inc = p['income']
    money = (f'<div style="font-size:13px;color:#474E5A;line-height:1.7;">Target ≈ <b>{usd0(inc["Target"]["monthly"])}</b>/mo · Valet ≈ <b>{usd0(inc["Valet"]["monthly"])}</b>/mo<br>'
             f'Your spending ≈ <b>{usd0(p["monthly_spending"])}</b>/mo · kept aside as a cushion: {p["cushion_pct"]}%<br>'
             f'Going to debts ≈ <b>{usd0(p["available_monthly"])}</b>/mo</div>')
    return f'''<!doctype html><html><body style="margin:0;padding:0;background:#F1F2F4;font-family:Inter,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F2F4;"><tr><td align="center" style="padding:20px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
<tr><td style="padding:4px 0 16px;"><div style="font-size:22px;font-weight:700;color:{TEXT};">Your Debt Payoff Plan</div>
<div style="font-size:13px;color:{MUTED};">Hi Jorgie, here is your plan as of {e(mname(p["month"]))}. Simple version: follow the steps below every payday.</div></td></tr>
{card('Where you stand', kpis)}
{card('What to do with every paycheck', checks)}
{card('The plan, step by step', f'<table role="presentation" cellpadding="0" cellspacing="0">{steps}</table>')}
{card('Your debts', debts_t or f'<div style="font-size:13px;color:{MUTED};">No debts logged yet.</div>')}
{card('The money behind the plan', money)}
<tr><td style="padding:4px 0 20px;font-size:12px;color:{MUTED};line-height:1.6;">Amounts are in US dollars and based on what you logged in your note. The Cozy House savings and your automatic $1,300 a month are never touched.
Log new paychecks with a + sign and payments like "Paid watch 300"; write "send plan" any time to get this email again.<br>
<a href="{e(url)}" style="color:{ACCENT};">Open the dashboard</a></td></tr>
</table></td></tr></table></body></html>'''


def email_text(p, url):
    L = [f"Your Debt Payoff Plan — {mname(p['month'])}", '',
         f"Total debt: {usd(p['total_debt'])}",
         f"Debt-free: {mname(p['debt_free_month']) if p['debt_free_month'] else 'after 6 years'} (goal {mname(p['goal_month'])})",
         f"Left by {mname(p['goal_month'])}: {usd0(p['left_at_goal'])}", '']
    for job in ('Target', 'Valet'):
        if p['per_check'][job]:
            L.append(f'Each {job} check: ' + ', '.join(f"{usd(x['amount'])} to {x['debt']}" for x in p['per_check'][job]))
    L.append('')
    L += [f'{i}. {t}' for i, t in enumerate(p['steps'], 1)]
    L += ['', f'Dashboard: {url}']
    return '\n'.join(L)


def main():
    args = [a for a in sys.argv[1:]]
    outdir = None
    if '--email' in args:
        k = args.index('--email'); outdir = args[k + 1]; del args[k:k + 2]
    if len(args) < 2: sys.exit(__doc__)
    fe, fd = args[0], args[1]
    today = date.fromisoformat(args[2]) if len(args) > 2 else date.today()
    expenses = json.load(open(fe, encoding='utf-8'))
    debts = json.load(open(fd, encoding='utf-8'))
    debts.setdefault('settings', dict(DEFAULTS)); debts.setdefault('accounts', []); debts.setdefault('payments', []); debts.setdefault('plan_requests', [])
    p = compute(expenses, debts, today)
    debts['plan'] = p
    json.dump(debts, open(fd, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if outdir:
        import os
        os.makedirs(outdir, exist_ok=True)
        url = 'https://gabinarvaezp.github.io/expenses/'
        open(os.path.join(outdir, 'plan.html'), 'w', encoding='utf-8').write(email_html(p, url))
        open(os.path.join(outdir, 'plan.txt'), 'w', encoding='utf-8').write(email_text(p, url))
    print(json.dumps({k: p[k] for k in ('total_debt', 'debt_free_month', 'left_at_goal', 'available_monthly', 'per_check', 'shortfall')}, indent=1))


if __name__ == '__main__':
    main()
