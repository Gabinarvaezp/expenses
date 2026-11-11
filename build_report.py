#!/usr/bin/env python3
"""Build the monthly expense report email (HTML + inline chart images).

Usage:
  python3 build_report.py expenses.json analysis.json savings.json 2026-10 household OUTDIR [dashboard_url]
  python3 build_report.py expenses.json analysis.json savings.json 2026-10 jorgie    OUTDIR [dashboard_url]
  python3 build_report.py expenses.json analysis.json savings.json 2026-10 gabby     OUTDIR [dashboard_url]
  python3 build_report.py expenses.json analysis.json savings.json 2026    household OUTDIR [dashboard_url]   (year in review)
  Add --debts debts.json (after debt_plan.py has run) to show the person's Free money in their own report.

Writes OUTDIR/report.html, OUTDIR/chart_month.png, OUTDIR/chart_category.png.
In the HTML, chart_month.png is cid:att0 and chart_category.png is cid:att1, so attach them
to the email in that order, both with inline = true.
"""
import json, sys, os, html
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December']
SHORT = [m[:3] for m in MONTHS]
BG = '#F1F2F4'; CARD = '#FFFFFF'; LINE = '#E3E6EA'; TEXT = '#2F3542'; MUTED = '#8A919C'
PURPLE = '#9B59D0'; UP = '#D64545'; DOWN = '#2E9E6A'; TREND = '#E9C94A'
PERSON = {'Gabby': '#E8697D', 'Jorgie': '#4B9FD5'}
PIE = ['#E8697D', '#4B9FD5', '#6CC3A0', '#F3D46B', '#F59E5B', '#A685D9', '#8FD0E8', '#B9DE8A', '#F4A6B8', '#9AA5B1', '#5C7FB8']
FONT = "'Helvetica Neue',Helvetica,Arial,sans-serif"
e = html.escape

for f in font_manager.findSystemFonts():
    if 'Inter-Regular' in f or 'Inter-Medium' in f or 'Inter-SemiBold' in f:
        font_manager.fontManager.addfont(f)
plt.rcParams['font.family'] = ['Inter', 'DejaVu Sans']

def usd(v): return ('-' if v < 0 else '') + '${:,.2f}'.format(abs(v))
def usd0(v): return '${:,.0f}'.format(v)
def cop(v): return ('-' if v < 0 else '') + 'COP {:,.0f}'.format(abs(v))
def copk(v): return '{:.2f}M'.format(v / 1e6) if abs(v) >= 1e6 else '{:.0f}K'.format(v / 1e3)
def usdk(v): return '${:.1f}K'.format(v / 1e3) if abs(v) >= 1e3 else '${:.0f}'.format(v)
def pct(v): return '{:.1f}%'.format(v)
def mname(m, short=False):
    if len(m) == 4: return m if short else f'Full year {m}'
    y, mm = map(int, m.split('-')); return f'{(SHORT if short else MONTHS)[mm-1]} {y}'
def inp(m, period): return m[:4] == period if len(period) == 4 else m == period

def summarize(rows, month, person, cur):
    allr = [r for r in rows if inp(r['month'], month) and (person == 'Household' or r['person'] == person)]
    inc = [r for r in allr if r['type'] == 'Income']
    s = [r for r in allr if r['type'] != 'Income']
    k = 'amount_' + cur
    out = {'rows': s, 'income_rows': inc, 'income': sum(r[k] for r in inc), 'total': sum(r[k] for r in s), 'fixed': sum(r[k] for r in s if r['type'] == 'Fixed'),
           'n_fixed': sum(1 for r in s if r['type'] == 'Fixed'), 'n_var': sum(1 for r in s if r['type'] != 'Fixed'),
           'usd': sum(r['amount_usd'] for r in s), 'cop': sum(r['amount_cop'] for r in s)}
    out['variable'] = out['total'] - out['fixed']
    return out

def pot_at(pt, m):
    ch = sorted(pt.get('changes') or [], key=lambda c: c['month'])
    if not ch: return float(pt['monthly'])
    v = float(ch[0].get('from', pt['monthly']))
    for c in ch:
        if c['month'] <= m: v = float(c['to'])
    return v

def overview(rows, sav, debts, person, period):
    """Money in, spent, saved (Cozy House + each personal savings pot) and free money left, for a month or a year.
    Same rules as compute_free in debt_plan.py (Jorgie's paychecks already arrive after his Cozy House saving)."""
    people = ['Gabby', 'Jorgie'] if person == 'Household' else [person]
    ms = sorted({r['month'] for r in rows} | {x['month'] for x in sav.get('entries', [])})
    ms = [m for m in ms if inp(m, period)]
    T = {'inc': 0.0, 'inc_cop': 0.0, 'n_inc': 0, 'fixed': 0.0, 'variable': 0.0, 'spent_cop': 0.0, 'from_free': 0.0,
         'cozy': 0.0, 'cozy_cop': 0.0, 'pots': {}, 'debts': 0.0, 'left': None, 'left_cop': None}
    for m in ms:
        rate = next((r['rate'] for r in rows if r['person'] == 'Gabby' and r['month'] == m and r.get('rate')), None) \
            or next((r['rate'] for r in reversed(rows) if r.get('rate')), 4000.0)
        for w in people:
            inc = inc_cop = fx = vr = sc = ff = cz = czc = pay = 0.0; n = 0
            for r in rows:
                if r['person'] != w or r['month'] != m: continue
                if r['type'] == 'Income': inc += r['amount_usd']; inc_cop += r['amount_cop']; n += 1
                elif r.get('from_free'): ff += r['amount_usd']
                else:
                    sc += r['amount_cop']
                    if r['type'] == 'Fixed': fx += r['amount_usd']
                    else: vr += r['amount_usd']
            for x in sav.get('entries', []):
                if x['person'] == w and x['month'] == m and x.get('kind') in ('Monthly saving', 'Extra saving'):
                    cz += float(x.get('amount_usd') or 0); czc += float(x.get('amount_cop') or 0)
            pots_u = pots_c = 0.0
            for pt in debts.get('pots', []):
                if pt.get('person') != w or pt['start_month'] > m or (pt.get('end_month') and m > pt['end_month']): continue
                v = pot_at(pt, m); cop_pt = pt.get('currency') == 'COP'
                u = v / rate if cop_pt else v
                q = T['pots'].setdefault((w, pt['name']), {'who': w, 'name': pt['name'], 'usd': 0.0, 'cop': 0.0 if cop_pt else None})
                q['usd'] += u
                if cop_pt: q['cop'] += v
                pots_u += u; pots_c += v if cop_pt else v * rate
            ids = {a['id'] for a in debts.get('accounts', []) if a.get('owner', 'Jorgie') == w}
            pay = sum(float(x['amount']) for x in debts.get('payments', []) if x['debt_id'] in ids and x['month'] == m)
            T['inc'] += inc; T['inc_cop'] += inc_cop; T['n_inc'] += n; T['fixed'] += fx; T['variable'] += vr; T['spent_cop'] += sc
            T['from_free'] += ff; T['cozy'] += cz; T['cozy_cop'] += czc; T['debts'] += pay
            if n:
                left = inc - (fx + vr + (cz if w == 'Gabby' else 0) + pots_u + pay)
                T['left'] = (T['left'] or 0) + left
                if w == 'Gabby':
                    T['left_cop'] = (T['left_cop'] or 0) + (inc_cop - sc - czc - pots_c - pay * rate)
    T['pots'] = list(T['pots'].values())
    return T

def card(title, body, sub='', center=False):
    al = 'text-align:center;' if center else ''
    s = f'<div style="font-size:14px;font-weight:700;color:{TEXT};{al}">{title}</div>'
    if sub: s += f'<div style="font-size:12px;color:{MUTED};margin-top:2px;{al}">{sub}</div>'
    return (f'<tr><td style="padding:0 24px 14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:4px;"><tr><td style="padding:16px 18px;">{s}'
            f'<div style="margin-top:12px;">{body}</div></td></tr></table></td></tr>')

def tip_html(t):
    if not t: return ''
    amt = usd0(t['amount']) + (f' ({cop(t["amount_cop"])})' if t.get('amount_cop') else '')
    soon = ' &rarr; paid off now' if t.get('clears') else f' &rarr; paid off {t["months_sooner"]} month{"s" if t["months_sooner"] != 1 else ""} sooner' if t['months_sooner'] > 0 else ''
    why = ', less interest' if t['reason'] == 'interest' else ''
    return (f'<div style="margin-top:12px;padding:10px 12px;border-radius:6px;background:#F5EEFB;font-size:13px;color:{TEXT};line-height:1.45;">'
            f'<b style="color:{PURPLE};">Tip:</b> {amt} extra to {e(t["debt"])}{soon}{why}. Keep {usd0(t["keep"])} for fun.</div>')

def dot(c, size=9): return f'<span style="display:inline-block;width:{size}px;height:{size}px;border-radius:50%;background:{c};margin-right:6px;vertical-align:middle;"></span>'

def main():
    args = sys.argv[1:]
    debts = {}
    if '--debts' in args:
        i = args.index('--debts'); debts = json.load(open(args[i + 1], encoding='utf-8')); del args[i:i + 2]
    fe, fa, fs, month, mode, outdir = args[0:6]
    url = args[6] if len(args) > 6 else ''
    sav = json.load(open(fs, encoding='utf-8')) if fs != '-' else {'plan': [], 'entries': []}
    os.makedirs(outdir, exist_ok=True)
    rows = json.load(open(fe, encoding='utf-8'))
    for r in rows:
        for k in ('amount', 'amount_usd', 'amount_cop', 'rate'): r[k] = float(r[k])
    analysis = json.load(open(fa, encoding='utf-8')) if fa != '-' else []
    person = {'jorgie': 'Jorgie', 'gabby': 'Gabby'}.get(mode, 'Household')
    cur = 'usd'
    money = usd
    year_mode = len(month) == 4
    months = sorted({r['month'] for r in rows if person == 'Household' or r['person'] == person})
    periods = sorted({m[:4] for m in months}) if year_mode else months
    if month not in periods: sys.exit(f'No expenses for {month}')
    i = periods.index(month); prev = periods[i - 1] if i > 0 else None
    S = summarize(rows, month, person, cur)
    P = summarize(rows, prev, person, cur) if prev else None
    an = next((a for a in analysis if a['month'] == month and a['person'] == person), None)
    var = [r for r in S['rows'] if r['type'] != 'Fixed']
    fixed = sorted([r for r in S['rows'] if r['type'] == 'Fixed'], key=lambda r: (r['person'], -r['amount_usd']))
    if year_mode:
        agg = {}
        for r in fixed:
            g = agg.setdefault((r['person'], r['item']), dict(r, amount=0.0, amount_usd=0.0, amount_cop=0.0, n=0))
            g['amount'] += r['amount']; g['amount_usd'] += r['amount_usd']; g['amount_cop'] += r['amount_cop']; g['n'] += 1
        for g in agg.values():
            g['item'] = f"{g['item']} ({g['n']} {'month' if g['n'] == 1 else 'months'})"
        fixed = sorted(agg.values(), key=lambda r: (r['person'], -r['amount_usd']))
    rate = next((r['rate'] for r in S['rows'] if r.get('rate')), None)

    # ---------- chart 1: spending by month ----------
    ms = [m for m in months if m[:4] == month] if year_mode else months[-6:]
    fig, ax = plt.subplots(figsize=(5.6, 2.6), dpi=200)
    xs = range(len(ms))
    totals = [summarize(rows, m, person, cur)['total'] for m in ms]
    hi = PERSON.get(person, PURPLE)
    cols = [hi if m == (ms[-1] if year_mode else month) else '#D9DDE3' for m in ms]
    w = 0.5 if len(ms) < 5 else 0.62
    ax.bar(xs, totals, w, color=cols, zorder=2)
    for x, t, m in zip(xs, totals, ms):
        cur_m = m == (ms[-1] if year_mode else month)
        ax.text(x, t + max(totals) * 0.03, usd0(t), ha='center', va='bottom', fontsize=8.5 if cur_m else 7.5,
                color=TEXT if cur_m else '#8A919C', fontweight='bold' if cur_m else 'normal')
    ax.set_xticks(list(xs)); ax.set_xticklabels([mname(m, True) for m in ms], fontsize=7.5, color='#6B717C')
    ax.set_yticks([]); ax.tick_params(axis='x', length=0)
    ax.set_ylim(0, max(totals) * 1.25 if max(totals) else 1)
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.spines['bottom'].set_visible(True); ax.spines['bottom'].set_color('#E3E6EA')
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, 'chart_month.png'), facecolor='white'); plt.close(fig)

    # ---------- chart 2: variable spending by category ----------
    cats = {}
    for r in var:
        c = cats.setdefault(r['category'], {'v': 0.0, 'n': 0, 'Gabby': 0.0, 'Jorgie': 0.0})
        c['v'] += r['amount_usd']; c['n'] += 1; c[r['person']] += r['amount_usd']
    cats = sorted(cats.items(), key=lambda kv: -kv[1]['v'])
    allcats = sorted({r['category'] for r in rows})
    ccol = {c: PIE[i % len(PIE)] for i, c in enumerate(allcats)}
    fig, ax = plt.subplots(figsize=(2.6, 2.6), dpi=200)
    if cats:
        ax.pie([d['v'] for _, d in cats], colors=[ccol[c] for c, _ in cats], startangle=90, counterclock=False,
               wedgeprops={'edgecolor': 'white', 'linewidth': 1.5, 'width': 0.38})
        tot_v = sum(d['v'] for _, d in cats)
        ax.text(0, 0.1, usd0(tot_v), ha='center', va='center', fontsize=13, fontweight='bold', color=TEXT)
        ax.text(0, -0.18, 'variable', ha='center', va='center', fontsize=7.5, color='#8A919C')
    ax.set_aspect('equal'); fig.tight_layout(pad=0.1)
    fig.savefig(os.path.join(outdir, 'chart_category.png'), facecolor='white'); plt.close(fig)

    # ---------- KPI tiles ----------
    def delta(a, b):
        if b is None: return f'<span style="color:{MUTED};">{"First year" if year_mode else "First month"}</span>'
        d = a - b; p = (d / b * 100) if b else 0
        col = UP if d > 0 else DOWN
        return f'<span style="color:{col};font-weight:700;">{"&#9650;" if d > 0 else "&#9660;"} {usdk(abs(d))} ({"+" if d > 0 else ""}{pct(p)})</span>'
    top = cats[0] if cats else None
    tiles = [
        ('Total Spent', delta(S['total'], P['total'] if P else None), money(S['total']),
         ('&asymp; ' + cop(S['cop'])) if person != 'Jorgie' else f"{S['n_var'] + S['n_fixed']} expenses"),
        ('Variable Spending', delta(S['variable'], P['variable'] if P else None), money(S['variable']), f"{S['n_var']} purchases"),
        ('Fixed Spending', delta(S['fixed'], P['fixed'] if P else None), money(S['fixed']), f"{S['n_fixed']} fixed expenses"),
        ('Top Category', '&nbsp;', e(top[0]) if top else '&mdash;', (money(top[1]['v']) + (' this year' if year_mode else ' this month')) if top else ''),
    ]
    def tile(t):
        label, d, v, cap = t
        size = '19px' if label.startswith('Top') else '24px'
        return (f'<td width="50%" valign="top" style="padding:0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="background:{CARD};border:1px solid {LINE};border-radius:4px;"><tr><td style="padding:14px 14px 16px;">'
                f'<div style="font-size:13px;font-weight:700;color:{TEXT};">{label}</div>'
                f'<div style="text-align:center;font-size:{size};font-weight:800;color:{TEXT};margin-top:10px;">{v}</div>'
                f'<div style="text-align:center;font-size:12px;color:{MUTED};margin-top:2px;">{cap}</div></td></tr></table></td>')
    kpis = (f'<tr><td style="padding:0 24px 14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            f'<tr>{tile(tiles[0])}<td width="12"></td>{tile(tiles[1])}</tr><tr><td colspan="3" height="12"></td></tr>'
            f'<tr>{tile(tiles[2])}<td width="12"></td>{tile(tiles[3])}</tr></table></td></tr>')

    # ---------- sections ----------
    monthly = f'<img src="cid:att0" width="514" alt="Spending by month" style="display:block;width:100%;max-width:514px;height:auto;border:0;">'

    legend_rows = ''.join(
        f'<tr><td style="padding:6px 0;font-size:13px;color:{TEXT};border-bottom:1px solid #F1F2F4;">{dot(ccol[c], 10)}{e(c)}</td>'
        f'<td align="right" style="padding:6px 0;font-size:13px;font-weight:700;color:{TEXT};white-space:nowrap;border-bottom:1px solid #F1F2F4;">{usd0(d["v"])}</td>'
        f'<td align="right" style="padding:6px 0 6px 10px;font-size:12px;color:{MUTED};white-space:nowrap;border-bottom:1px solid #F1F2F4;">{pct(d["v"] / S["variable"] * 100 if S["variable"] else 0)}</td></tr>'
        for c, d in cats)
    pie = (f'<div style="text-align:center;"><img src="cid:att1" width="200" alt="Spending by category" style="display:inline-block;width:200px;max-width:70%;height:auto;border:0;"></div>'
           f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:360px;margin:14px auto 0;">{legend_rows}</table>')

    analysis_html = ''
    if an:
        analysis_html = card('Monthly Analysis',
            f'<div style="font-size:17px;font-weight:700;color:{TEXT};line-height:1.3;">{e(an["title"])}</div>'
            + ''.join(f'<div style="font-size:14px;color:#474E5A;line-height:1.5;margin-top:8px;">&bull;&nbsp; {e(t.strip().lstrip("-•· ").strip())}</div>'
                    for t in an["text"].split("\n") if t.strip()))

    who_html = ''
    if person == 'Household':
        parts = ''
        for name in ('Gabby', 'Jorgie'):
            G = summarize(rows, month, name, 'usd')
            share = G['usd'] / S['usd'] * 100 if S['usd'] else 0
            main = usd(G['total'])
            sub = f'{pct(share)} of Cozy House spending' + (f' &middot; &asymp; {cop(G["cop"])}' if name == 'Gabby' else '')
            Gp = summarize(rows, prev, name, 'usd') if prev else None
            chg = ''
            if Gp and Gp['total']:
                d = (G['total'] - Gp['total']) / Gp['total'] * 100
                chg = f' &middot; <span style="color:{UP if d > 0 else DOWN};font-weight:700;">{"&#9650;" if d > 0 else "&#9660;"} {pct(abs(d))}</span> vs. {SHORT[int(prev[5:]) - 1]}'
            parts += (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;"><tr>'
                      f'<td style="font-size:14px;font-weight:700;color:{TEXT};">{dot(PERSON[name], 10)}{name}</td>'
                      f'<td align="right" style="font-size:19px;font-weight:800;color:{TEXT};">{main}</td></tr>'
                      f'<tr><td colspan="2" style="font-size:12px;color:{MUTED};padding-top:2px;">{sub}{chg}</td></tr>'
                      f'<tr><td colspan="2" style="padding-top:6px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF0F3;border-radius:4px;">'
                      f'<tr><td width="{max(1, round(share))}%" style="background:{PERSON[name]};height:8px;line-height:8px;font-size:0;border-radius:4px;">&nbsp;</td>'
                      f'<td style="height:8px;line-height:8px;font-size:0;">&nbsp;</td></tr></table></td></tr></table>')
        who_html = ''  # Cozy House is shared: no per-person split or comparison

    # savings
    savings_html = ''
    ents = [x for x in sav.get('entries', []) if person == 'Household' or x['person'] == person]
    end = month + '-12' if year_mode else month
    upto = [x for x in ents if x['month'] <= end]
    if upto:
        inper = [x for x in upto if inp(x['month'], month) and x['kind'] != 'Starting balance']
        bal_u = sum(float(x['amount_usd']) for x in upto); bal_c = sum(float(x['amount_cop']) for x in upto)
        span_word = 'this year' if year_mode else 'this month'
        head = (f'<div style="font-size:28px;font-weight:800;color:{DOWN};">{usd(bal_u)}</div>'
                f'<div style="font-size:12px;color:{MUTED};margin-top:2px;">'
                + ('' if person == 'Jorgie' else f'&asymp; {cop(bal_c)} &middot; ') + f'saved as of {"the end of " + month if year_mode else mname(month)}</div>')
        lines = ''
        for name in (['Gabby', 'Jorgie'] if person == 'Household' else [person]):
            mine = [x for x in upto if x['person'] == name]
            if not mine: continue
            pl = next((x for x in sav.get('plan', []) if x['person'] == name), None)
            got = [x for x in inper if x['person'] == name]
            started = any(x['kind'] == 'Starting balance' and inp(x['month'], month) for x in mine)
            if name == 'Gabby':
                saved = cop(sum(float(x['amount_cop']) for x in got)); bal = usd(sum(float(x['amount_usd']) for x in mine)) + f' <span style="font-weight:400;color:{MUTED};font-size:12px;">&asymp; {cop(sum(float(x["amount_cop"]) for x in mine))}</span>'
            else:
                saved = usd(sum(float(x['amount_usd']) for x in got)); bal = usd(sum(float(x['amount_usd']) for x in mine))
            if got: note = f'Saved {span_word}: <b style="color:{DOWN};">+{saved}</b>'
            elif started: note = 'Starting balance recorded'
            else: note = f'Nothing saved {span_word}'
            if pl and not year_mode:
                note += f' &middot; plan {cop(pl["monthly"]) if pl["currency"] == "COP" else usd(pl["monthly"])} a month' + (', automatic' if pl.get('automatic') else '')
            lines += (f'<tr><td style="padding:10px 0 0;font-size:14px;font-weight:700;color:{TEXT};">{dot(PERSON[name], 10)}{name}</td>'
                      f'<td align="right" style="padding:10px 0 0;font-size:16px;font-weight:800;color:{TEXT};white-space:nowrap;">{bal}</td></tr>'
                      f'<tr><td colspan="2" style="font-size:12px;color:#5D6470;padding:2px 0 10px;border-bottom:1px solid #EEF0F3;">{note}</td></tr>')
        title_s = 'Cozy House Savings' if person == 'Household' else f'{person}’s Savings'
        savings_html = card(title_s, head + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;">{lines}</table>')

    # heatmap
    hm = [m for m in months if m[:4] == month][-6:] if year_mode else months[-4:]
    heat_rows = [r for r in rows if r['type'] == 'Variable' and r['month'] in hm and (person == 'Household' or r['person'] == person)]
    hv = {}
    for r in heat_rows: hv[(r['category'], r['month'])] = hv.get((r['category'], r['month']), 0) + r['amount_usd']
    hcats = sorted({c for c, _ in hv}, key=lambda c: -sum(v for (cc, _), v in hv.items() if cc == c))
    hmax = max(hv.values()) if hv else 1
    def heat(v):
        t = 0.08 + 0.92 * v / hmax
        a = (0xEA, 0xF3, 0xFB); b = (0x1C, 0x67, 0xA8)
        c = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
        return '#%02X%02X%02X' % c, ('#FFFFFF' if t > 0.55 else TEXT)
    hhead = ''.join(f'<td align="right" style="padding:6px 8px;font-size:12px;font-weight:700;color:{PURPLE if (m == month or year_mode) else TEXT};border-bottom:1px solid {LINE};">{mname(m, True)}</td>' for m in hm)
    hbody = ''
    for c in hcats:
        cells = ''
        for m in hm:
            v = hv.get((c, m))
            if v is None: cells += '<td style="background:#FAFBFC;border:1px solid #fff;"></td>'
            else:
                bg, fg = heat(v)
                cells += f'<td align="right" style="background:{bg};color:{fg};padding:7px 8px;font-size:12px;border:1px solid #fff;white-space:nowrap;">{usd0(v)}</td>'
        hbody += f'<tr><td style="padding:7px 8px 7px 0;font-size:12px;font-weight:700;color:{TEXT};white-space:nowrap;">{e(c)}</td>{cells}</tr>'
    heatmap = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
               f'<tr><td style="padding:6px 8px 6px 0;font-size:12px;font-weight:700;color:{TEXT};border-bottom:1px solid {LINE};">Category</td>{hhead}</tr>{hbody}</table>')

    def amount_txt(r):
        if r['currency'] == 'COP':
            return f'{usd(r["amount_usd"])}<div style="font-size:11px;color:{MUTED};font-weight:400;">{cop(r["amount"])}</div>'
        return usd(r['amount'])
    def rows_html(items, who):
        out = ''
        for r in items:
            w = ''
            auto = (f' <span style="font-size:10px;font-weight:700;color:{PURPLE};background:#F5EEFB;border-radius:3px;padding:1px 5px;">AUTO</span>' if r.get('origin') == 'auto' else '')
            out += (f'<tr><td style="padding:9px 0;border-bottom:1px solid #EEF0F3;font-size:13px;color:{TEXT};">{e(r["item"])}{auto}'
                    f'<div style="font-size:11px;color:{MUTED};margin-top:2px;">{w}{e(r["category"])}</div></td>'
                    f'<td align="right" valign="top" style="padding:9px 0;border-bottom:1px solid #EEF0F3;font-size:13px;font-weight:700;color:{TEXT};white-space:nowrap;">{amount_txt(r)}</td></tr>')
        return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{out}</table>'
    who = person == 'Household'
    if who:
        topbuy = sorted(var, key=lambda r: -r['amount_usd'])[:5]
        top_title = 'Top 5 Purchases'
    else:
        topbuy = sorted(var, key=lambda r: -r['amount_usd'])[:5]
        top_title = 'Top 5 Purchases'

    # free money (what was left this month rolls into a personal pot); only with --debts and logged income
    free_html = ''
    fr = (((debts.get('plan') or {}).get('people') or {}).get(person) or {}).get('free') if not who and not year_mode else None
    mrow = next((x for x in (fr or {}).get('months', []) if x['month'] == month), None)
    if mrow:
        left = mrow['left']
        cap = (f'In {usd0(mrow["income"])} &middot; fixed {usd0(mrow["fixed"])} &middot; variable {usd0(mrow["variable"])}'
               + (f' &middot; saved {usd0(mrow["saved"])}' if mrow['saved'] else '') + (f' &middot; debts {usd0(mrow["debts"])}' if mrow['debts'] else ''))
        tot = f'{usd(fr["balance"])}' + (f' <span style="font-weight:400;color:{MUTED};font-size:12px;">&asymp; {cop(fr["balance_cop"])}</span>' if fr.get('balance_cop') is not None else '')
        free_html = card('Free Money',
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            f'<tr><td style="font-size:14px;font-weight:700;color:{TEXT};">Left over in {mname(month)}</td><td align="right" style="font-size:18px;font-weight:800;color:{DOWN if left > 0 else TEXT};">{("+" + usd(left)) if left > 0 else usd(0)}</td></tr>'
            f'<tr><td colspan="2" style="font-size:12px;color:{MUTED};padding:2px 0 10px;border-bottom:1px solid #EEF0F3;">{cap}</td></tr>'
            f'<tr><td style="font-size:14px;font-weight:700;color:{TEXT};padding-top:10px;">Ready to use</td><td align="right" style="font-size:16px;font-weight:800;color:{TEXT};padding-top:10px;white-space:nowrap;">{tot}</td></tr></table>'
            + tip_html(fr.get('tip')))

    # month overview: money in, spent, saved (Cozy House + personal savings), free money
    O = overview(rows, sav, debts, person, month)
    span_o = 'this year' if year_mode else 'this month'
    gab = person == 'Gabby'
    def ov_row(label, val, cap, color=None, bold=True):
        return (f'<tr><td style="padding:10px 0 0;font-size:14px;font-weight:700;color:{TEXT};">{label}</td>'
                f'<td align="right" style="padding:10px 0 0;font-size:17px;font-weight:800;color:{color or TEXT};white-space:nowrap;">{val}</td></tr>'
                f'<tr><td colspan="2" style="font-size:12px;color:{MUTED};padding:2px 0 10px;border-bottom:1px solid #EEF0F3;">{cap}</td></tr>')
    def sub_row(label, val):
        return (f'<tr><td style="padding:5px 0 5px 14px;font-size:13px;color:#474E5A;border-bottom:1px solid #F4F5F7;">{e(label)}</td>'
                f'<td align="right" style="padding:5px 0;font-size:13px;font-weight:700;color:{TEXT};white-space:nowrap;border-bottom:1px solid #F4F5F7;">{val}</td></tr>')
    inc_cap = (f'{O["n_inc"]} payment{"s" if O["n_inc"] != 1 else ""} logged' + (f' &middot; &asymp; {cop(O["inc_cop"])}' if gab else '')) if O['n_inc'] else f'No income logged {span_o}'
    sp_cap = f'Fixed {usd0(O["fixed"])} &middot; variable {usd0(O["variable"])}' + (f' &middot; &asymp; {cop(O["spent_cop"])}' if gab else '') + (f' &middot; plus {usd0(O["from_free"])} paid with free money' if O['from_free'] else '')
    pots_u = sum(x['usd'] for x in O['pots'])
    sv_cap = f'Cozy House {usd0(O["cozy"])} &middot; personal savings {usd0(pots_u)}' if (O['cozy'] or pots_u) else f'Nothing saved {span_o}'
    subs = ''
    if O['cozy']: subs += sub_row('Cozy House', cop(O['cozy_cop']) if gab else usd0(O['cozy']))
    for x in O['pots']:
        subs += sub_row((x['who'] + ' · ' if person == 'Household' else '') + x['name'], cop(x['cop']) if (x['cop'] is not None and person != 'Household') else usd0(x['usd']))
    if O['left'] is None:
        fm_val, fm_col, fm_cap = '&mdash;', None, 'Log income to see what is left'
    else:
        fm_val, fm_col = usd(O['left']), (DOWN if O['left'] >= 0 else UP)
        fm_cap = ('Left over ' + span_o + ', added to Free money') + (f' &middot; after {usd0(O["debts"])} paid to debts' if O['debts'] else '') + (f' &middot; &asymp; {cop(O["left_cop"])}' if (gab and O['left_cop'] is not None) else '')
    overview_html = card(('Year' if year_mode else 'Month') + ' Overview',
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        + ov_row('Money in', usd(O['inc']), inc_cap)
        + ov_row('Spent', usd(O['fixed'] + O['variable']), sp_cap)
        + ov_row('Saved', usd(O['cozy'] + pots_u), sv_cap) + subs
        + ov_row('Free money', fm_val, fm_cap, fm_col) + '</table>')

    title = ((f'Cozy House {month} Wrapped' if who else f'{person}’s {month} Wrapped') if year_mode
             else ('Cozy House' if who else f'{person}’s Report'))
    span = 'this year' if year_mode else 'this month'
    greeting = f'Hi Gabby and Jorgie, here is how Cozy House spent {span}.' if who else f'Hi {person}, here is how you spent {span}.'
    button = (f'<tr><td align="center" style="padding:6px 24px 26px;"><a href="{e(url)}" style="display:inline-block;background:{PURPLE};color:#ffffff;'
              f'text-decoration:none;font-size:14px;font-weight:700;padding:12px 26px;border-radius:4px;">Open Dashboard</a></td></tr>') if url else ''
    rate_note = f' Gabby’s pesos converted at {cop(rate)} per US dollar (TRM).' if (rate and person != 'Jorgie') else ''
    pre = f'{"The household" if who else "You"} spent {usd(S["total"])} in {mname(month)}.'

    out = f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} &middot; {mname(month)}</title></head>
<body style="margin:0;padding:0;background:{BG};font-family:{FONT};">
<div style="display:none;max-height:0;overflow:hidden;">{pre}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};"><tr><td align="center" style="padding:24px 10px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{BG};">
  <tr><td style="background:{CARD};border:1px solid {LINE};border-radius:4px 4px 0 0;padding:14px 20px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td valign="middle"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="background:{PURPLE};color:#ffffff;font-size:11px;font-weight:800;width:30px;height:30px;text-align:center;border-radius:6px;">G&amp;J</td>
        <td style="padding-left:10px;font-size:15px;font-weight:700;color:{TEXT};">Expenses<div style="font-size:11px;font-weight:400;color:{MUTED};">Gabby &amp; Jorgie</div></td>
      </tr></table></td>
      <td align="right" valign="middle" style="font-size:13px;color:{TEXT};"><b>Month:</b> {mname(month)}</td>
    </tr></table>
  </td></tr>
  <tr><td style="background:{PURPLE};height:3px;line-height:3px;font-size:0;">&nbsp;</td></tr>
  <tr><td style="padding:22px 24px 6px;">
    <div style="font-size:24px;font-weight:500;color:{TEXT};">{title}</div>
    <div style="font-size:14px;color:{MUTED};margin-top:6px;padding-bottom:14px;border-bottom:1px solid #DADDE2;">{greeting}</div>
  </td></tr>
  <tr><td height="14"></td></tr>
  {kpis}
  {overview_html}
  {card('Spending by Category', pie, 'Variable spending ' + span, center=True)}
  {card('Month by Month', monthly, 'Total spent each month' + ('' if year_mode else ' · ' + mname(month) + ' in color'), center=True)}
  {analysis_html}
  {who_html}
  {card('Category by Month', heatmap, 'Variable spending in US dollars. Darker cells mean more spending.')}
  {card(top_title, rows_html(topbuy, who))}
  {card('Income', rows_html(sorted(S['income_rows'], key=lambda r: (r['month'], -r['amount_usd'])), who)) if (S['income_rows'] and not who) else ''}
  {card('Fixed Expenses', rows_html(fixed, who) if fixed else f'<div style="font-size:13px;color:{MUTED};">No fixed expenses this month</div>', 'Automatic debits and monthly bills' + (f' &middot; {money(S["fixed"])} in total' if fixed else ''))}
  {free_html}
  {savings_html}
  {button}
  <tr><td style="padding:0 24px 20px;font-size:11px;color:{MUTED};line-height:1.5;text-align:center;">Built from your iPhone expense notes.{rate_note}</td></tr>
</table></td></tr></table></body></html>'''
    open(os.path.join(outdir, 'report.html'), 'w', encoding='utf-8').write(out)
    print('ok', os.path.join(outdir, 'report.html'))

if __name__ == '__main__':
    main()
