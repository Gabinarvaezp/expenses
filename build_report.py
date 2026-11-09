#!/usr/bin/env python3
"""Build the monthly expense report email (HTML + inline chart images).

Usage:
  python3 build_report.py expenses.json analysis.json 2026-10 household OUTDIR [dashboard_url]
  python3 build_report.py expenses.json analysis.json 2026-10 jorgie    OUTDIR [dashboard_url]

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
    y, mm = map(int, m.split('-')); return f'{(SHORT if short else MONTHS)[mm-1]} {y}'

def summarize(rows, month, person, cur):
    s = [r for r in rows if r['month'] == month and (person == 'Household' or r['person'] == person)]
    k = 'amount_' + cur
    out = {'rows': s, 'total': sum(r[k] for r in s), 'fixed': sum(r[k] for r in s if r['type'] == 'Fixed'),
           'n_fixed': sum(1 for r in s if r['type'] == 'Fixed'), 'n_var': sum(1 for r in s if r['type'] != 'Fixed'),
           'usd': sum(r['amount_usd'] for r in s), 'cop': sum(r['amount_cop'] for r in s)}
    out['variable'] = out['total'] - out['fixed']
    return out

def card(title, body, sub=''):
    s = f'<div style="font-size:14px;font-weight:700;color:{TEXT};">{title}</div>'
    if sub: s += f'<div style="font-size:12px;color:{MUTED};margin-top:2px;">{sub}</div>'
    return (f'<tr><td style="padding:0 24px 14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:4px;"><tr><td style="padding:16px 18px;">{s}'
            f'<div style="margin-top:12px;">{body}</div></td></tr></table></td></tr>')

def dot(c, size=9): return f'<span style="display:inline-block;width:{size}px;height:{size}px;border-radius:50%;background:{c};margin-right:6px;vertical-align:middle;"></span>'

def main():
    fe, fa, month, mode, outdir = sys.argv[1:6]
    url = sys.argv[6] if len(sys.argv) > 6 else ''
    os.makedirs(outdir, exist_ok=True)
    rows = json.load(open(fe, encoding='utf-8'))
    for r in rows:
        for k in ('amount', 'amount_usd', 'amount_cop', 'rate'): r[k] = float(r[k])
    analysis = json.load(open(fa, encoding='utf-8')) if fa != '-' else []
    person = 'Jorgie' if mode == 'jorgie' else 'Household'
    cur = 'usd'
    money = usd
    months = sorted({r['month'] for r in rows if person == 'Household' or r['person'] == person})
    if month not in months: sys.exit(f'No expenses for {month}')
    i = months.index(month); prev = months[i - 1] if i > 0 else None
    S = summarize(rows, month, person, cur)
    P = summarize(rows, prev, person, cur) if prev else None
    an = next((a for a in analysis if a['month'] == month and a['person'] == person), None)
    var = [r for r in S['rows'] if r['type'] != 'Fixed']
    fixed = sorted([r for r in S['rows'] if r['type'] == 'Fixed'], key=lambda r: (r['person'], -r['amount_usd']))
    rate = next((r['rate'] for r in S['rows'] if r.get('rate')), None)

    # ---------- chart 1: spending by month ----------
    ms = months[-6:]
    fig, ax = plt.subplots(figsize=(5.6, 2.6), dpi=200)
    xs = range(len(ms))
    if person == 'Household':
        series = [('Gabby', [summarize(rows, m, 'Gabby', cur)['total'] for m in ms], PERSON['Gabby']),
                  ('Jorgie', [summarize(rows, m, 'Jorgie', cur)['total'] for m in ms], PERSON['Jorgie'])]
    else:
        series = [('Fixed', [summarize(rows, m, person, cur)['fixed'] for m in ms], '#C7CDD6'),
                  ('Variable', [summarize(rows, m, person, cur)['variable'] for m in ms], PERSON[person])]
    totals = [summarize(rows, m, person, cur)['total'] for m in ms]
    varline = [summarize(rows, m, person, cur)['variable'] for m in ms]
    bottom = [0] * len(ms)
    w = 0.42 if len(ms) < 5 else 0.6
    for name, vals, col in series:
        ax.bar(xs, vals, w, bottom=bottom, color=col, label=name, zorder=2,
               alpha=1)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.plot(list(xs), varline, color=TREND, lw=2.2, marker='o', ms=6, mec='white', mew=1.4, zorder=3, label='Variable trend')
    for x, t, m in zip(xs, totals, ms):
        ax.text(x, t * 1.03, usd0(t), ha='center', va='bottom', fontsize=7.5, color=TEXT, fontweight='semibold')
    ax.set_xticks(list(xs)); ax.set_xticklabels([mname(m, True) for m in ms], fontsize=7.5, color='#6B717C')
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usdk(v)))
    ax.tick_params(axis='y', labelsize=7, colors='#6B717C', length=0); ax.tick_params(axis='x', length=0)
    ax.set_ylim(0, max(totals) * 1.22)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
    ax.grid(axis='y', color='#ECEEF1', lw=0.8, zorder=0)
    for s in ax.spines.values(): s.set_visible(False)
    leg = ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.12), ncol=3, frameon=False, fontsize=7.5, handlelength=1, handleheight=0.8)
    for t in leg.get_texts(): t.set_color(TEXT); t.set_fontweight('semibold')
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
    fig, ax = plt.subplots(figsize=(2.4, 2.4), dpi=200)
    if cats:
        ax.pie([d['v'] for _, d in cats], colors=[ccol[c] for c, _ in cats], startangle=90, counterclock=False,
               wedgeprops={'edgecolor': 'white', 'linewidth': 1})
    ax.set_aspect('equal'); fig.tight_layout(pad=0.1)
    fig.savefig(os.path.join(outdir, 'chart_category.png'), facecolor='white'); plt.close(fig)

    # ---------- KPI tiles ----------
    def delta(a, b):
        if b is None: return f'<span style="color:{MUTED};">First month</span>'
        d = a - b; p = (d / b * 100) if b else 0
        col = UP if d > 0 else DOWN
        return f'<span style="color:{col};font-weight:700;">{"&#9650;" if d > 0 else "&#9660;"} {usdk(abs(d))} ({"+" if d > 0 else ""}{pct(p)})</span>'
    top = cats[0] if cats else None
    tiles = [
        ('Total Spent', delta(S['total'], P['total'] if P else None), money(S['total']),
         ('&asymp; ' + cop(S['cop'])) if person == 'Household' else f"{S['n_var'] + S['n_fixed']} expenses"),
        ('Variable Spending', delta(S['variable'], P['variable'] if P else None), money(S['variable']),
         f"{pct(S['variable'] / S['total'] * 100 if S['total'] else 0)} of total &middot; {S['n_var']} purchases"),
        ('Fixed &amp; Recurring', delta(S['fixed'], P['fixed'] if P else None), money(S['fixed']), f"{S['n_fixed']} bills every month"),
        ('Top Variable Category', '&nbsp;', e(top[0]) if top else '&mdash;', (money(top[1]['v']) + ' this month') if top else ''),
    ]
    def tile(t):
        label, d, v, cap = t
        size = '19px' if label.startswith('Top') else '24px'
        return (f'<td width="50%" valign="top" style="padding:0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="background:{CARD};border:1px solid {LINE};border-radius:4px;"><tr><td style="padding:14px 14px 16px;">'
                f'<div style="font-size:13px;font-weight:700;color:{TEXT};">{label}</div>'
                f'<div style="text-align:center;margin-top:8px;font-size:12px;">{d}</div>'
                f'<div style="text-align:center;font-size:{size};font-weight:800;color:{TEXT};margin-top:2px;">{v}</div>'
                f'<div style="text-align:center;font-size:12px;color:{MUTED};margin-top:2px;">{cap}</div></td></tr></table></td>')
    kpis = (f'<tr><td style="padding:0 24px 14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            f'<tr>{tile(tiles[0])}<td width="12"></td>{tile(tiles[1])}</tr><tr><td colspan="3" height="12"></td></tr>'
            f'<tr>{tile(tiles[2])}<td width="12"></td>{tile(tiles[3])}</tr></table></td></tr>')

    # ---------- sections ----------
    monthly = f'<img src="cid:att0" width="514" alt="Spending by month" style="display:block;width:100%;max-width:514px;height:auto;border:0;">'

    legend_rows = ''.join(
        f'<tr><td style="padding:4px 0;font-size:12px;color:{TEXT};">{dot(ccol[c])}{e(c)}</td>'
        f'<td align="right" style="padding:4px 0;font-size:12px;font-weight:700;color:{TEXT};white-space:nowrap;">{usd0(d["v"])}</td>'
        f'<td align="right" style="padding:4px 0 4px 8px;font-size:12px;color:{MUTED};white-space:nowrap;">{pct(d["v"] / S["variable"] * 100 if S["variable"] else 0)}</td></tr>'
        for c, d in cats)
    pie = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
           f'<td width="170" valign="middle"><img src="cid:att1" width="160" alt="Variable spending by category" style="display:block;width:160px;height:auto;border:0;"></td>'
           f'<td valign="middle" style="padding-left:14px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{legend_rows}</table></td></tr></table>')

    analysis_html = ''
    if an:
        analysis_html = card('Monthly Analysis',
            f'<div style="font-size:17px;font-weight:700;color:{TEXT};line-height:1.3;">{e(an["title"])}</div>'
            f'<div style="font-size:14px;color:#474E5A;line-height:1.65;margin-top:8px;">{e(an["text"])}</div>')

    who_html = ''
    if person == 'Household':
        parts = ''
        for name in ('Gabby', 'Jorgie'):
            G = summarize(rows, month, name, 'usd')
            share = G['usd'] / S['usd'] * 100 if S['usd'] else 0
            main = usd(G['total'])
            sub = f'{pct(share)} of household spending' + (f' &middot; &asymp; {cop(G["cop"])}' if name == 'Gabby' else '')
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
        who_html = card('Who Spent What', parts, 'All amounts in USD; Gabby\u2019s pesos shown small as a reference')

    # heatmap
    hm = months[-4:]
    heat_rows = [r for r in rows if r['type'] != 'Fixed' and r['month'] in hm and (person == 'Household' or r['person'] == person)]
    hv = {}
    for r in heat_rows: hv[(r['category'], r['month'])] = hv.get((r['category'], r['month']), 0) + r['amount_usd']
    hcats = sorted({c for c, _ in hv}, key=lambda c: -sum(v for (cc, _), v in hv.items() if cc == c))
    hmax = max(hv.values()) if hv else 1
    def heat(v):
        t = 0.08 + 0.92 * v / hmax
        a = (0xEA, 0xF3, 0xFB); b = (0x1C, 0x67, 0xA8)
        c = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
        return '#%02X%02X%02X' % c, ('#FFFFFF' if t > 0.55 else TEXT)
    hhead = ''.join(f'<td align="right" style="padding:6px 8px;font-size:12px;font-weight:700;color:{PURPLE if m == month else TEXT};border-bottom:1px solid {LINE};">{mname(m, True)}</td>' for m in hm)
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
            w = (dot(PERSON[r['person']], 8) + e(r['person']) + ' &middot; ') if who else ''
            out += (f'<tr><td style="padding:9px 0;border-bottom:1px solid #EEF0F3;font-size:13px;color:{TEXT};">{e(r["item"])}'
                    f'<div style="font-size:11px;color:{MUTED};margin-top:2px;">{w}{e(r["category"])}</div></td>'
                    f'<td align="right" valign="top" style="padding:9px 0;border-bottom:1px solid #EEF0F3;font-size:13px;font-weight:700;color:{TEXT};white-space:nowrap;">{amount_txt(r)}</td></tr>')
        return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{out}</table>'
    who = person == 'Household'
    if who:
        topbuy = [r for p in ('Gabby', 'Jorgie') for r in sorted([x for x in var if x['person'] == p], key=lambda r: -r['amount_usd'])[:3]]
        top_title = 'Top 3 Purchases Each'
    else:
        topbuy = sorted(var, key=lambda r: -r['amount_usd'])[:5]
        top_title = 'Top 5 Purchases'

    title = 'Household Report' if who else 'Jorgie’s Report'
    greeting = 'Hi Gabby and Jorgie, here is how the household spent this month.' if who else 'Hi Jorgie, here is how you spent this month.'
    button = (f'<tr><td align="center" style="padding:6px 24px 26px;"><a href="{e(url)}" style="display:inline-block;background:{PURPLE};color:#ffffff;'
              f'text-decoration:none;font-size:14px;font-weight:700;padding:12px 26px;border-radius:4px;">Open Dashboard</a></td></tr>') if url else ''
    rate_note = f' Gabby’s pesos converted at {cop(rate)} per US dollar (TRM).' if (rate and who) else ''
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
  {card('Spending by Month', monthly)}
  {card('Variable Spending by Category', pie)}
  {analysis_html}
  {who_html}
  {card('Category by Month', heatmap, 'Variable spending in US dollars. Darker cells mean more spending.')}
  {card(top_title, rows_html(topbuy, who))}
  {card('Fixed &amp; Recurring Bills', rows_html(fixed, who) if fixed else f'<div style="font-size:13px;color:{MUTED};">No fixed bills this month</div>')}
  {button}
  <tr><td style="padding:0 24px 20px;font-size:11px;color:{MUTED};line-height:1.5;text-align:center;">Built from your iPhone expense notes.{rate_note}</td></tr>
</table></td></tr></table></body></html>'''
    open(os.path.join(outdir, 'report.html'), 'w', encoding='utf-8').write(out)
    print('ok', os.path.join(outdir, 'report.html'))

if __name__ == '__main__':
    main()
