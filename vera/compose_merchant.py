"""Rule composers for merchant-scope trigger kinds.

Each composer uses one signal, pulls every number from ctx.facts and returns None when
its required fact is missing so the generic composer takes over. No number is
hard-coded in a template.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .facts import Ctx, human
from .voice import cta_choice, hinglish_for, salutation, tone


@dataclass
class Draft:
    body: str
    cta: str  # "binary" | "choice" | "open_ended" | "none"
    rationale: str


# ---------- small helpers ----------

def commas(s: str) -> str:
    return f"{int(s):,}" if re.fullmatch(r"\d{4,}", s or "") else s


def unsigned(s: str) -> str:
    return (s or "").lstrip("+-")


def window_h(s: str | None, hinglish: bool = False) -> str:
    m = re.fullmatch(r"(\d+)d", s or "")
    if m:
        return f"pichhle {m.group(1)} din" if hinglish else f"the last {m.group(1)} days"
    return human(s) if s else ("pichhle hafte" if hinglish else "the last week")


_ABBR = re.compile(r"(?:\b(?:Dr|Mr|Mrs|Ms|St|vs|p|No|approx)|\b[A-Z])\.$")


def first_sentence(s: str | None) -> str:
    if not s:
        return ""
    s = s.strip()
    for m in re.finditer(r"[.!?](?=\s|$)", s):
        head = s[: m.end()]
        if m.group(0) == "." and _ABBR.search(head):
            continue
        return head
    return s


def moved(delta: str, hinglish: bool = False) -> str:
    """'-12%' -> 'down 12%' / '12% kam'; '+18%' -> 'up 18%' / '18% zyada'."""
    neg = delta.startswith("-")
    v = unsigned(delta)
    if hinglish:
        return f"{v} {'kam' if neg else 'zyada'}"
    return f"{'down' if neg else 'up'} {v}"


def end(s: str) -> str:
    s = s.strip()
    return s if s.endswith((".", "!", "?", "\"")) else s + "."


def join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def has(ctx: Ctx, *keys: str) -> bool:
    return all(ctx.facts.get(k) for k in keys)


def metric_word(m: str | None, hinglish: bool = False) -> str:
    return {"calls": "calls", "views": "profile views", "directions": "direction requests",
            "leads": "leads", "review_count": "reviews", "ctr": "click-through"}.get(m or "", human(m or "numbers"))


def ctr_line(ctx: Ctx, h: bool) -> str:
    f = ctx.facts
    if not has(ctx, "ctr", "peer_ctr"):
        return ""
    if h:
        return f"Aapka profile CTR {f['ctr']} hai, jabki similar {ctx.slug or 'businesses'} ka average {f['peer_ctr']}."
    return f"Your profile CTR is {f['ctr']} against a {f['peer_ctr']} average for similar {ctx.slug or 'businesses'}."


def L(h: bool, en: str, hi: str) -> str:
    return hi if h else en


# ---------- composers ----------

def research_digest(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    if not has(ctx, "digest_title", "digest_source"):
        return None
    trial = f" (n={commas(f['digest_trial_n'])})" if f.get("digest_trial_n") else ""
    cohort = ""
    if f.get("high_risk_adults"):
        cohort = L(h, f"You have {f['high_risk_adults']} high-risk adults on your books — this one directly affects their recall interval.",
                   f"Aapke paas {f['high_risk_adults']} high-risk adult patients hain — unke recall interval pe iska seedha asar hai.")
    elif f.get("lapsed_180d"):
        cohort = L(h, f"Relevant for the {f['lapsed_180d']} patients who haven't been back in 6+ months.",
                   f"Aapke {f['lapsed_180d']} lapsed patients ke liye relevant hai.")
    body = join(
        f"{s}, {tone(ctx, 'news', h)} — {f['digest_source']}{trial}: {end(f['digest_title'])}",
        first_sentence(f.get("digest_summary")),
        cohort,
        cta_choice(L(h, "get a patient recall message based on this", "patient recall message ka draft"),
                   "skip", h),
    )
    return Draft(body, "binary", "Research digest item cited with source, tied to the merchant's own patient cohort.")


def _lc(s: str) -> str:
    """Lower-case a leading capital unless it starts an acronym (e.g. "DCI")."""
    return s[0].lower() + s[1:] if len(s) > 1 and s[0].isupper() and not s[1].isupper() else s


def regulation_change(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    deadline = f.get("p_deadline_iso_date") or f.get("p_deadline_iso")
    if not deadline and not f.get("digest_title"):
        return None
    head = f.get("digest_title") or L(h, "a new compliance rule", "ek naya compliance rule")
    src = f" ({f['digest_source']})" if f.get("digest_source") else ""
    body = join(
        f"{s}, {tone(ctx, 'alert', h)}: {head}{src}.",
        first_sentence(f.get("digest_summary")),
        L(h, f"Deadline is {deadline} — {_lc(end(f.get('digest_actionable') or 'worth auditing your setup before then'))}",
          f"Deadline {deadline} hai — {_lc(end(f.get('digest_actionable') or 'usse pehle setup audit kar lein'))}") if deadline else "",
        cta_choice(L(h, "get a one-page audit checklist", "one-page audit checklist"),
                   L(h, "tell me you're already compliant", "already compliant"), h),
    )
    return Draft(body, "binary", "Regulatory change with deadline from the payload; offers a concrete checklist.")


def perf_dip(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    if not has(ctx, "p_delta_pct"):
        return None
    metric = metric_word(f.get("p_metric"))
    base = ""
    if f.get("p_vs_baseline"):
        base = L(h, f" against your usual baseline of {f['p_vs_baseline']}", f" (aapka usual baseline {f['p_vs_baseline']} tha)")
    body = join(
        L(h, f"{s}, your {metric} are down {unsigned(f['p_delta_pct'])} over {window_h(f.get('p_window'))}{base}.",
          f"{s}, {window_h(f.get('p_window'), True)} mein aapke {metric} {unsigned(f['p_delta_pct'])} gir gaye hain{base}."),
        ctr_line(ctx, h),
        L(h, "Usually a stale offer or profile is the cause, and it's fixable this week.",
          "Aksar stale offer ya profile wajah hoti hai — is hafte fix ho sakta hai."),
        cta_choice(L(h, "let me refresh your offer and post today", "aaj hi offer aur post refresh") if f.get("active_offer")
                   else L(h, "let me set up an offer and a fresh post today", "aaj hi ek offer aur fresh post set up"),
                   L(h, "see the full breakdown first", "pehle poora breakdown"), h),
    )
    return Draft(body, "binary", "Performance dip from the payload, benchmarked against the peer CTR.")


def renewal_due(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    days = f.get("p_days_remaining") or f.get("sub_days_remaining")
    if not days:
        return None
    plan = f.get("p_plan") or f.get("plan") or "current"
    amt = f" (₹{commas(f['p_renewal_amount'])})" if f.get("p_renewal_amount") else ""
    value = ""
    if has(ctx, "views_30d", "calls_30d"):
        value = L(h, f"Over the last 30 days your listing brought {commas(f['views_30d'])} views and {f['calls_30d']} calls — that stops if it lapses.",
                  f"Pichhle 30 din mein listing se {commas(f['views_30d'])} views aur {f['calls_30d']} calls aaye — lapse hone par yeh ruk jayega.") \
            if f.get("perf_window_days") == "30" else ""
    body = join(
        L(h, f"{s}, your {plan} plan{amt} is due for renewal in {days} days.",
          f"{s}, aapka {plan} plan{amt} {days} din mein renew hona hai."),
        value,
        cta_choice(L(h, "get the renewal link", "renewal link"), L(h, "ask for a quick call first", "pehle ek quick call"), h),
    )
    return Draft(body, "binary", "Renewal window with days remaining and amount from the payload.")


def festival_upcoming(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    fest = f.get("p_festival")
    if not fest:
        return None
    when = ""
    if f.get("p_days_until") and f.get("p_date_date"):
        when = L(h, f" is {f['p_days_until']} days away ({f['p_date_date']})", f" {f['p_days_until']} din door hai ({f['p_date_date']})")
    elif f.get("p_date_date"):
        when = f" — {f['p_date_date']}"
    offer = ""
    if f.get("active_offer"):
        offer = L(h, f"Your \"{f['active_offer']}\" offer is a ready-made festive hook if we lead with it early.",
                  f"Aapka \"{f['active_offer']}\" offer festive hook ban sakta hai agar hum ise jaldi push karein.")
    body = join(
        L(h, f"{s}, {tone(ctx, 'opp', h)} — {fest}{when}. Festive bookings fill up early.",
          f"{s}, {tone(ctx, 'opp', h)} — {fest}{when}. Festive bookings jaldi fill hoti hain."),
        offer,
        cta_choice(L(h, f"get a {fest} offer post draft", f"{fest} offer post ka draft"), L(h, "revisit this later", "baad mein"), h),
    )
    return Draft(body, "binary", "Upcoming festival from the payload paired with the merchant's live offer.")


ASK_TEMPLATES = {
    "what_service_in_demand_this_week": ("Which service are customers asking for most this week?",
                                         "Is hafte customers sabse zyada kaunsi service maang rahe hain?"),
}


def curious_ask_due(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    key = f.get("p_ask_template")
    en, hi = ASK_TEMPLATES.get(key or "", (f"Quick question: {human(key)}?" if key else "What's been busiest for you this week?",
                                             f"Ek sawaal: {human(key)}?" if key else "Is hafte sabse zyada kya chal raha hai?"))
    where = f.get("locality") or f.get("city") or ""
    views = f" — your profile had {commas(f['views_30d'])} views last month" if f.get("views_30d") else ""
    body = join(
        L(h, f"{s}, quick one{views}.", f"{s}, quick sawaal{views.replace('your profile had', 'aapke profile pe').replace('views last month', 'views aaye pichhle mahine')}."),
        L(h, f"I'll turn your answer into a Google post for people searching in {where}." if where else "I'll turn your answer into a Google post.",
          f"Aapke jawaab se main {where} ke searchers ke liye Google post bana dungi." if where else "Aapke jawaab se main Google post bana dungi."),
        L(h, en, hi),
    )
    return Draft(body, "open_ended", "Low-friction curiosity ask that turns the answer into content.")


def winback_eligible(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    days = f.get("p_days_since_expiry")
    if not days:
        return None
    dip = f" {unsigned(f['p_perf_dip_pct'])}" if f.get("p_perf_dip_pct") else ""
    lapsed = f.get("p_lapsed_customers_added_since_expiry")
    body = join(
        L(h, f"{s}, it's been {days} days since your plan lapsed. Since then your listing's performance is down{dip}" + (f" and {lapsed} more customers have gone quiet." if lapsed else "."),
          f"{s}, plan lapse hue {days} din ho gaye. Tab se listing ki performance{dip} kam hai" + (f" aur {lapsed} aur customers wapas nahi aaye." if lapsed else ".")),
        L(h, "Restarting now lets me send those customers a win-back offer straight away.",
          "Abhi restart karein toh main un customers ko turant win-back offer bhej sakti hoon."),
        cta_choice(L(h, "restart with a win-back push", "win-back push ke saath restart"), L(h, "have a quick chat first", "pehle quick baat"), h),
    )
    return Draft(body, "binary", "Lapsed subscription: loss since expiry quantified from the payload.")


def ipl_match_today(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    match = f.get("p_match")
    if not match:
        return None
    at = f" at {f['p_venue']}" if f.get("p_venue") else ""
    t = f", {f['p_match_time_iso_time']}" if f.get("p_match_time_iso_time") else ""
    usable, weekday_only = f.get("active_offer"), None
    if usable and ctx.payload.get("is_weeknight") is False and re.search(r"\b(mon|tue|wed|thu|fri)\b", usable, re.I):
        usable, weekday_only = None, usable  # weekday-only offer does not apply to a weekend match
    area = f.get("locality")
    where = L(h, f" for {area}", f" {area} ke liye") if area else ""
    if usable:
        offer = L(h, f"Push \"{usable}\" as a match-night deal{where} before the toss.", f"Toss se pehle \"{usable}\" ko{where} match-night deal ki tarah push karein.")
    elif weekday_only:
        offer = L(h, f"Your \"{weekday_only}\" doesn't cover tonight, so a match-night combo post{where} before the toss is the play — after the toss, orders are already placed elsewhere.",
                  f"Aapka \"{weekday_only}\" aaj lagu nahi hota, toh toss se pehle{where} match-night combo post daalein — toss ke baad orders kahin aur ja chuke hote hain.")
    else:
        offer = L(h, f"A match-night combo post{where} before the toss usually lifts delivery orders.", f"Toss se pehle{where} match-night combo post se delivery orders badhte hain.")
    body = join(
        L(h, f"{s}, {match} today{at}{t}.", f"{s}, aaj {match} hai" + (f" — {f['p_venue']}" if f.get("p_venue") else "") + f"{t}."),
        offer,
        cta_choice(L(h, "get a match-night post now", "abhi match-night post"), L(h, "skip today", "aaj skip"), h),
    )
    return Draft(body, "binary", "Local IPL match today from the payload, tied to the live offer.")


def review_theme_emerged(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    theme = f.get("p_theme")
    if not theme:
        return None
    n = f.get("p_occurrences_30d")
    trend = f" and {human(f['p_trend'])}" if f.get("p_trend") else ""
    quote = f" One says: \"{f['p_common_quote']}\"." if f.get("p_common_quote") else ""
    body = join(
        L(h, f"{s}, {n + ' recent reviews mention' if n else 'reviews are mentioning'} {human(theme)}{trend}.{quote}",
          f"{s}, {n + ' recent reviews mein' if n else 'reviews mein'} {human(theme)} ki baat aa rahi hai{trend.replace(' and ', ', trend ')}.{quote}"),
        L(h, "A calm public reply plus one fix you can name usually stops the slide.",
          "Ek shaant public reply aur ek clear fix batane se yeh ruk jaata hai."),
        cta_choice(L(h, "get a reply template for these reviews", "in reviews ke liye reply template"), "skip", h),
    )
    return Draft(body, "binary", "Emerging review theme with count and verbatim quote from the payload.")


def milestone_reached(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    now, goal = f.get("p_value_now"), f.get("p_milestone_value")
    if not (now and goal):
        return None
    metric = metric_word(f.get("p_metric"))
    gap = f" — just {f['milestone_gap']} away from {goal}" if f.get("milestone_gap") else f" — {goal} is in reach"
    body = join(
        L(h, f"{s}, you're at {now} {metric}{gap}.", f"{s}, aap {now} {metric} pe ho" + (f" — {goal} se bas {f['milestone_gap']} door." if f.get("milestone_gap") else ".")),
        L(h, "A short thank-you note to your regulars this week gets you there.", "Is hafte regulars ko ek chhota thank-you note bhejein — milestone ho jayega."),
        cta_choice(L(h, "get a review-request message to send", "review-request message ka draft"), L(h, "revisit later", "baad mein"), h),
    )
    return Draft(body, "binary", "Imminent milestone from the payload with the exact gap.")


def active_planning_intent(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    topic = f.get("p_intent_topic")
    if not topic:
        return None
    said = f.get("p_merchant_last_message") or f.get("last_merchant_message")
    stop = "" if said and said.rstrip().endswith((".", "!", "?")) else "."
    quote = L(h, f" You asked: \"{said}\"{stop}", f" Aapne poocha tha: \"{said}\"{stop}") if said else ""
    anchor = L(h, f"I'd build it on your existing \"{f['active_offer']}\" so pricing stays familiar,",
               f"Isse aapke \"{f['active_offer']}\" offer pe build karenge taaki pricing familiar rahe,") if f.get("active_offer") \
        else L(h, "I'd keep it to one simple package with a clear price,", "Ek simple package aur clear price rakhenge,")
    body = join(
        L(h, f"{s}, here's a first cut for the {human(topic)}.{quote}", f"{s}, {human(topic)} ka first draft ready hai.{quote}"),
        L(h, f"{anchor} with a fixed schedule, a booking cut-off and one launch post.",
          f"{anchor} fixed schedule, booking cut-off aur ek launch post ke saath."),
        L(h, "Parents plan these early, so the sooner it's live the more of the batch fills before others announce theirs.",
          "Parents yeh jaldi plan karte hain — jitni jaldi live hoga, utna batch doosron se pehle bharega.")
        if re.search(r"kid|child", f.get("p_intent_topic", ""), re.I) else "",
        L(h, f"Your {commas(f['views_30d'])} profile views last month are the audience for that launch post.",
          f"Aapke pichhle mahine ke {commas(f['views_30d'])} profile views hi us launch post ki audience hain.") if f.get("views_30d") else "",
        cta_choice(L(h, "see the full draft", "poora draft"), L(h, "suggest changes first", "pehle changes"), h),
    )
    return Draft(body, "binary", "Merchant already expressed intent; responds with a concrete first draft.")


SEASON_NOTES = {"post_resolution_window_apr_jun": ("the usual post-resolution lull (Apr–Jun)", "post-resolution wala normal lull (Apr–Jun)")}


def seasonal_perf_dip(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    if not has(ctx, "p_delta_pct"):
        return None
    note_en, note_hi = SEASON_NOTES.get(f.get("p_season_note", ""), (human(f.get("p_season_note") or "a seasonal dip"),) * 2)
    metric = metric_word(f.get("p_metric"))
    strength = ""
    if has(ctx, "ctr", "peer_ctr"):
        strength = L(h, f"Your CTR is still {f['ctr']} vs a {f['peer_ctr']} peer average, so the profile itself is fine.",
                     f"Aapka CTR abhi bhi {f['ctr']} hai (peer average {f['peer_ctr']}), toh profile theek hai.")
    body = join(
        L(h, f"{s}, {metric} are down {unsigned(f['p_delta_pct'])} over {window_h(f.get('p_window'))} — that's {note_en}, not something you did.",
          f"{s}, {window_h(f.get('p_window'), True)} mein {metric} {unsigned(f['p_delta_pct'])} kam hain — yeh {note_hi} hai, aapki galti nahi."),
        strength,
        L(h, "Best use of a quiet stretch is keeping current members showing up.", "Quiet time mein current members ko regular rakhna sabse zaroori hai."),
        cta_choice(L(h, "get a member-referral post", "member-referral post"), "skip", h),
    )
    return Draft(body, "binary", "Expected seasonal dip reframed with the merchant's above-peer CTR.")


def supply_alert(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    mol = f.get("p_molecule")
    if not mol:
        return None
    batches = [v for k, v in sorted(f.items()) if re.fullmatch(r"p_affected_batches_\d+", k)]
    b = f" batches {', '.join(batches)}" if batches else ""
    mfr = f" ({f['p_manufacturer']})" if f.get("p_manufacturer") else ""
    src = f" per {f['digest_source']}" if f.get("digest_source") else ""
    rx = L(h, "Customers you dispensed these batches to should hear it from you before they hear it elsewhere — that's what keeps them with you.",
           "Jin customers ko yeh batch diya gaya, unhe kahin aur se pehle aapse pata chalna chahiye — isi se bharosa bana rehta hai.")
    body = join(
        L(h, f"{s}, {tone(ctx, 'alert', h)}: {mol}{b}{mfr} are under a voluntary recall{src}.",
          f"{s}, {tone(ctx, 'alert', h)}: {mol}{b}{mfr} pe voluntary recall hai" + (f" (source: {f['digest_source']})." if f.get("digest_source") else ".")),
        L(h, "Pull them from the shelf and swap via your distributor.", "Shelf se hata kar distributor se replace karwa lein."),
        rx,
        cta_choice(L(h, "get a customer WhatsApp note drafted", "customers ke liye WhatsApp note ka draft"),
                   L(h, "tell me it's already handled", "already handled"), h),
    )
    return Draft(body, "binary", "Urgent batch recall with batch numbers and source; action-first.")


def _trend_phrase(raw: str) -> str:
    m = re.fullmatch(r"(.+?)_demand_([+-]?\d+(?:\.\d+)?)", raw)
    if m:
        item = m.group(1).replace("_", " & " if m.group(1) == "cold_cough" else " ")
        return f"{item} {m.group(2)}%"
    return human(raw)


def category_seasonal(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    trends = [_trend_phrase(v) for k, v in sorted(f.items(), key=lambda kv: kv[0]) if re.fullmatch(r"p_trends_\d+", k)]
    if not trends:
        return None
    season = human(f.get("p_season") or "this season")
    src = f" ({f['digest_source']})" if f.get("digest_source") else ""
    body = join(
        L(h, f"{s}, {season} demand shift{src}: {', '.join(trends)}.", f"{s}, {season} ka demand shift{src}: {', '.join(trends)}."),
        L(h, "Moving the rising items to the counter and front shelf now catches it before stock-outs.",
          "Badhne wale items ko abhi counter aur front shelf pe le aayein, stock-out se pehle."),
        cta_choice(L(h, "get a shelf plan plus a post", "shelf plan aur ek post"), "skip", h),
    )
    return Draft(body, "binary", "Seasonal category demand trends straight from the payload.")


def gbp_unverified(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    path = human(f.get("p_verification_path") or "postcard or phone call")
    uplift = f.get("p_estimated_uplift_pct")
    gain = L(h, f" — verifying is estimated to lift visibility by about {unsigned(uplift)}", f" — verify karne se visibility lagbhag {unsigned(uplift)} badh sakti hai") if uplift else ""
    calls = L(h, f" on top of your current {f['calls_30d']} calls a month", f", abhi ke {f['calls_30d']} calls/month ke upar") if f.get("calls_30d") and uplift else ""
    body = join(
        L(h, f"{s}, your Google profile for {f.get('merchant_name', 'the store')} still isn't verified{gain}{calls}.",
          f"{s}, {f.get('merchant_name', 'store')} ka Google profile abhi verified nahi hai{gain}{calls}."),
        L(h, f"It takes one {path} step.", f"Bas ek {path.replace(' or ', ' ya ')} step hai."),
        cta_choice(L(h, "start verification now", "abhi verification shuru"), L(h, "do it later this week", "is hafte baad mein"), h),
    )
    return Draft(body, "binary", "Unverified profile with estimated uplift from the payload.")


def cde_opportunity(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    title = f.get("digest_title")
    if not title:
        return None
    when = ", ".join(x for x in (f.get("digest_date"), f.get("digest_time")) if x)
    credits = f.get("p_credits") or f.get("digest_credits")
    fee = human(f.get("p_fee")) if f.get("p_fee") else ""
    bits = ", ".join(x for x in (when, f"{credits} CDE credits" if credits else "", fee) if x)
    body = join(
        f"{s}, {tone(ctx, 'news', h)} — {title}" + (f" ({bits})." if bits else "."),
        first_sentence(f.get("digest_summary")),
        cta_choice(L(h, "get the registration link", "registration link"), "skip", h),
    )
    return Draft(body, "binary", "CDE event from the digest with date, credits and fee.")


def competitor_opened(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    name = f.get("p_competitor_name")
    if not name:
        return None
    dist = f" {f['p_distance_km']} km away" if f.get("p_distance_km") else " nearby"
    opened = f" on {f['p_opened_date_date']}" if f.get("p_opened_date_date") else ""
    offer = f", leading with \"{f['p_their_offer']}\"" if f.get("p_their_offer") else ""
    edge = ""
    clinical = ctx.slug == "dentists"
    who = "patients" if clinical else "customers"
    strength_en, strength_hi = ("quality of care and continuity", "quality of care aur continuity") if clinical \
        else ("service and consistency", "service aur consistency")
    views = L(h, f" Your {commas(f['views_30d'])} profile views last month are the {who} they'll target first.",
              f" Aapke pichhle mahine ke {commas(f['views_30d'])} profile views wahi log hain jinhe woh pehle target karenge.") if f.get("views_30d") else ""
    if f.get("active_offer"):
        edge = L(h, f"Matching on price isn't the answer — position \"{f['active_offer']}\" on {strength_en}.{views}",
                 f"Price pe match karna zaroori nahi — \"{f['active_offer']}\" ko {strength_hi} pe position karein.{views}")
    elif f.get("review_pos_quote"):
        edge = L(h, f"Matching on price isn't the answer — your reviews say \"{f['review_pos_quote']}\". That's the post to run.{views}",
                 f"Price pe match karna zaroori nahi — aapke reviews kehte hain \"{f['review_pos_quote']}\". Wahi post chalayein.{views}")
    body = join(
        L(h, f"{s}, {name} opened{dist}{opened}{offer}.", f"{s}, {name}" + (f" {f['p_opened_date_date']} ko" if f.get("p_opened_date_date") else "") + (f" {f['p_distance_km']} km door" if f.get("p_distance_km") else " paas mein") + f" khula hai{offer}."),
        edge,
        cta_choice(L(h, "get a post built on your strength", "aapki strength wala post"), L(h, "just watch for now", "abhi sirf watch"), h),
    )
    return Draft(body, "binary", "New nearby competitor from the payload; counters with the merchant's review strength.")


def perf_spike(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    if not has(ctx, "p_delta_pct"):
        return None
    metric = metric_word(f.get("p_metric"))
    base = f" (baseline {f['p_vs_baseline']})" if f.get("p_vs_baseline") else ""
    driver = L(h, f" — looks driven by your {human(f['p_likely_driver'])}", f" — lagta hai aapke {human(f['p_likely_driver'])} ki wajah se") if f.get("p_likely_driver") else ""
    body = join(
        L(h, f"{s}, {metric} are up {unsigned(f['p_delta_pct'])} over {window_h(f.get('p_window'))}{base}{driver}.",
          f"{s}, {window_h(f.get('p_window'), True)} mein {metric} {unsigned(f['p_delta_pct'])} upar hain{base}{driver}."),
        L(h, "Members follow momentum — a follow-up post while it's hot keeps the run going; left alone, a spike like this fades within days.",
          "Members momentum follow karte hain — abhi follow-up post daalein toh run chalta rahega; chhod diya toh aisa spike kuch din mein utar jaata hai.")
        if ctx.slug == "gyms" else
        L(h, "A follow-up post while it's hot usually extends the run; left alone, a spike like this fades within days.",
          "Abhi follow-up post daalein toh momentum chalta rahega; chhod diya toh aisa spike kuch din mein utar jaata hai."),
        cta_choice(L(h, "get a follow-up post", "follow-up post"), "skip", h),
    )
    return Draft(body, "binary", "Performance spike with its likely driver from the payload.")


def dormant_with_vera(ctx: Ctx) -> Draft | None:
    f, h, s = ctx.facts, hinglish_for(ctx), salutation(ctx)
    days = f.get("p_days_since_last_merchant_message")
    if not days:
        return None
    topic = L(h, f" (last time it was about {human(f['p_last_topic'])})", f" (pichhli baar {human(f['p_last_topic'])} ki baat hui thi)") if f.get("p_last_topic") else ""
    since = ""
    if f.get("views_30d") and f.get("calls_30d"):
        since = L(h, f"Last month {commas(f['views_30d'])} people viewed your profile but only {f['calls_30d']} called — those are customers slipping past.",
                  f"Pichhle mahine {commas(f['views_30d'])} logon ne profile dekha par sirf {f['calls_30d']} ne call kiya — yeh customers haath se nikal rahe hain.")
    elif f.get("views_delta_7d"):
        since = L(h, f"Meanwhile profile views are {moved(f['views_delta_7d'])} this week.", f"Is beech profile views is hafte {moved(f['views_delta_7d'], True)} hain.")
    body = join(
        L(h, f"{s}, it's been {days} days since we last spoke{topic}.", f"{s}, humari baat hue {days} din ho gaye{topic}."),
        since,
        cta_choice(L(h, "get a short status update", "ek short status update"), L(h, "pause these messages", "messages pause"), h),
    )
    return Draft(body, "binary", "Re-engage a dormant merchant with a single concrete number.")


MERCHANT_COMPOSERS: dict[str, Callable[[Ctx], Draft | None]] = {
    "research_digest": research_digest,
    "regulation_change": regulation_change,
    "perf_dip": perf_dip,
    "renewal_due": renewal_due,
    "festival_upcoming": festival_upcoming,
    "curious_ask_due": curious_ask_due,
    "winback_eligible": winback_eligible,
    "ipl_match_today": ipl_match_today,
    "review_theme_emerged": review_theme_emerged,
    "milestone_reached": milestone_reached,
    "active_planning_intent": active_planning_intent,
    "seasonal_perf_dip": seasonal_perf_dip,
    "supply_alert": supply_alert,
    "category_seasonal": category_seasonal,
    "gbp_unverified": gbp_unverified,
    "cde_opportunity": cde_opportunity,
    "competitor_opened": competitor_opened,
    "perf_spike": perf_spike,
    "dormant_with_vera": dormant_with_vera,
}
