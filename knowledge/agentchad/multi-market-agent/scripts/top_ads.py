# Library v2, 2026-11-09 (agentchad.io). Read-only. Keys only from your own environment.
"""top_ads.py: list your top ads by spend from the Meta Marketing API (read-only), so you know which videos to translate.

  top_ads.py [--days 30] [--limit 20] [--min-spend 0] [--json out.json] [--dry-run]

Env (your own account, never written into a file):
  META_ACCESS_TOKEN    a token with ads_read permission (Meta Business settings -> System users, or Graph API Explorer)
  META_AD_ACCOUNT_ID   your ad account number, with or without the "act_" prefix
  META_API_VERSION     optional, default v21.0

--dry-run prints the request it would make (without the token) and stops. Nothing is changed in your account.
The output gives ad names; match each name to the MASTER video file on your computer (the editor's export or the
creator's original). Never translate a video downloaded back from the ad platform: it is re-compressed.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PURCHASE_TYPES = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")


def build_url(account, version, days, limit):
    acct = account if account.startswith("act_") else f"act_{account}"
    until = dt.date.today() - dt.timedelta(days=1)
    since = until - dt.timedelta(days=days - 1)
    params = {
        "level": "ad",
        "fields": "ad_id,ad_name,campaign_name,spend,impressions,actions,action_values,purchase_roas",
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}, separators=(",", ":")),
        "sort": json.dumps(["spend_descending"], separators=(",", ":")),
        "limit": str(min(max(limit, 1), 500)),
    }
    return f"https://graph.facebook.com/{version}/{acct}/insights?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except (ValueError, KeyError):
            msg = body[:300]
        sys.exit(f"Meta API error {e.code}: {msg}")


def first_value(items, types):
    for t in types:
        for it in items or []:
            if it.get("action_type") == t:
                return float(it.get("value", 0))
    return 0.0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=30, help="look-back window ending yesterday (default 30)")
    p.add_argument("--limit", type=int, default=20, help="how many ads to list (default 20)")
    p.add_argument("--min-spend", type=float, default=0.0, help="skip ads below this spend")
    p.add_argument("--json", help="also write the rows to this JSON file")
    p.add_argument("--dry-run", action="store_true", help="print the request and stop (no token needed)")
    a = p.parse_args()

    account = os.environ.get("META_AD_ACCOUNT_ID", "").strip()
    version = os.environ.get("META_API_VERSION", "v21.0").strip()
    if a.dry_run:
        url = build_url(account or "<META_AD_ACCOUNT_ID>", version, a.days, a.limit)
        print("GET", urllib.parse.unquote(url))
        print("Header: Authorization: Bearer <META_ACCESS_TOKEN>  (read-only; nothing is changed)")
        return
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token or not account:
        sys.exit("Set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID in your shell first (see --help). Nothing was called.")

    rows, url = [], build_url(account, version, a.days, a.limit)
    while url and len(rows) < a.limit:
        page = get(url, token)
        for r in page.get("data", []):
            spend = float(r.get("spend", 0))
            if spend < a.min_spend:
                continue
            purchases = first_value(r.get("actions"), PURCHASE_TYPES)
            value = first_value(r.get("action_values"), PURCHASE_TYPES)
            roas = first_value(r.get("purchase_roas"), PURCHASE_TYPES) or (value / spend if spend else 0.0)
            rows.append({"ad_id": r.get("ad_id"), "ad_name": r.get("ad_name"), "campaign": r.get("campaign_name"),
                         "spend": round(spend, 2), "purchases": int(purchases), "roas": round(roas, 2)})
        url = page.get("paging", {}).get("next")
    rows = rows[:a.limit]
    if not rows:
        print("No ads with spend in this window.")
        return
    print(f"Top {len(rows)} ads by spend, last {a.days} days (spend in your account currency):")
    print(f"{'#':>3} {'spend':>10} {'purch':>6} {'roas':>5}  ad name")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3} {r['spend']:>10.2f} {r['purchases']:>6} {r['roas']:>5.2f}  {r['ad_name']}")
    print("\nNext: find the MASTER file for each ad you want to translate (match the code or name in the ad name).")
    print("Spend alone is not proof: judge winners on enough spend AND results, by your own threshold.")
    if a.json:
        json.dump(rows, open(a.json, "w"), ensure_ascii=False, indent=1)
        print("wrote", a.json)


if __name__ == "__main__":
    main()
