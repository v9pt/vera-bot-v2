"""Rule composers for customer-scope kinds, sent as the merchant (merchant_on_behalf).

Never mention Vera or magicpin. Open with "Hi <name>, <owner> from <merchant name> here." (owner
omitted when already in the shop name; "Hi, ..." when the customer is unknown). Slot labels
come verbatim from the payload; a price appears only when it is in an active offer.
"""
from __future__ import annotations

import re
from typing import Callable

from .compose_merchant import Draft, L, join
from .facts import Ctx, human
from .voice import customer_name, customer_parent, customer_wants_hinglish, hinglish_for


def cust_hinglish(ctx: Ctx) -> bool:
    """Customer's own language preference; without a customer context, the merchant's rule."""
    if ctx.customer:
        return customer_wants_hinglish(ctx.customer)
    return hinglish_for(ctx)


def greeting(ctx: Ctx) -> str:
    name = customer_parent(ctx) or customer_name(ctx)
    shop = ctx.facts.get("merchant_name") or "your neighbourhood store"
    owner = ctx.facts.get("owner_first_name")
    if owner and owner.lower() not in shop.lower():
        who = f"{'Dr. ' if ctx.slug == 'dentists' else ''}{owner} from {shop}"
    else:
        who = shop
    return f"Hi {name}, {who} here." if name else f"Hi, {who} here."


def slot_labels(ctx: Ctx) -> list[str]:
    out = []
    for key in ("available_slots", "next_session_options", "slots"):
        for item in ctx.payload.get(key) or []:
            if isinstance(item, dict) and item.get("label"):
                out.append(str(item["label"]))
            elif isinstance(item, str):
                out.append(item)
    return out[:2]


def slot_cta(ctx: Ctx, h: bool, fallback_a: tuple[str, str], fallback_b: tuple[str, str]) -> tuple[str, str]:
    slots = slot_labels(ctx)
    if len(slots) >= 2:
        return (f"Reply 1 — {slots[0]}, ya 2 — {slots[1]}." if h else f"Reply 1 for {slots[0]}, or 2 for {slots[1]}.", "choice")
    if len(slots) == 1:
        return (f"Reply 1 — {slots[0]} confirm, ya 2 — koi aur time." if h
                else f"Reply 1 to confirm {slots[0]}, or 2 for a different time.", "binary")
    a, b = (fallback_a[1], fallback_b[1]) if h else (fallback_a[0], fallback_b[0])
    return (f"Reply 1 — {a}, ya 2 — {b}." if h else f"Reply 1 to {a}, or 2 to {b}.", "binary")


def matching_offer(ctx: Ctx, *words: str) -> str | None:
    """An active offer whose title mentions one of the words."""
    for key in ("active_offer", "active_offer_2"):
        title = ctx.facts.get(key)
        if title and any(w and w.lower() in title.lower() for w in words):
            return title
    return None


def recall_due(ctx: Ctx) -> Draft | None:
    f, h = ctx.facts, cust_hinglish(ctx)
    service = human(f.get("p_service_due") or "check-up")
    last = f.get("p_last_service_date_date") or f.get("customer_last_visit")
    due = f.get("p_due_date_date")
    words = [w for w in re.split(r"\W+", service) if len(w) > 3]
    offer = matching_offer(ctx, *words)
    body = join(
        greeting(ctx),
        L(h, f"Your {service} is due" + (f" on {due}" if due else "") + (f" (last visit {last})." if last else "."),
          f"Aapki {service} due hai" + (f" — {due} tak" if due else "") + (f" (last visit {last})." if last else ".")),
        L(h, f"Current offer: {offer}.", f"Offer chal raha hai: {offer}.") if offer else "",
        slot_cta(ctx, h, ("book a slot", "slot book karein"), ("skip for now", "abhi nahi"))[0],
    )
    return Draft(body, slot_cta(ctx, h, ("", ""), ("", ""))[1], "Recall due date and real slots from the payload.")


PROGRAMS = {"skin_prep_program_30day": "30-day skin prep program"}


def wedding_package_followup(ctx: Ctx) -> Draft | None:
    f, h = ctx.facts, cust_hinglish(ctx)
    wedding = f.get("p_wedding_date_date")
    if not wedding:
        return None
    step_raw = ctx.payload.get("next_step_window_open")
    step = PROGRAMS.get(step_raw or "", human(step_raw or "pre-wedding prep"))
    days = f" — {f['p_days_to_wedding']} days to go" if f.get("p_days_to_wedding") else ""
    trial = f" Since your trial on {f['p_trial_completed_date']}," if f.get("p_trial_completed_date") else ""
    body = join(
        greeting(ctx),
        L(h, f"Your wedding is on {wedding}{days}.{trial} now is the right window to start the {step}.",
          f"Aapki shaadi {wedding} ko hai{days}.{trial} ab {step} shuru karne ka sahi time hai."),
        slot_cta(ctx, h, ("book a start date", "start date book karein"), ("get the details first", "pehle details"))[0],
    )
    return Draft(body, "binary", "Bridal follow-up timed off the wedding date in the payload.")


def customer_lapsed_hard(ctx: Ctx) -> Draft | None:
    f, h = ctx.facts, cust_hinglish(ctx)
    days = f.get("p_days_since_last_visit")
    if not days:
        return None
    focus = human(f.get("p_previous_focus") or "")
    months = f.get("p_previous_membership_months")
    work = ""
    if months and focus:
        work = L(h, f" Your {months} months of {focus.replace(' ', '-')} work is worth protecting.", f" Aapke {months} months ka {focus} progress bachana zaroori hai.")
    offer = f.get("active_offer")
    body = join(
        greeting(ctx),
        L(h, f"It's been {days} days since your last session.{work}", f"Aapke last session ko {days} din ho gaye.{work}"),
        L(h, f"Come back with our {offer}.", f"Wapas aaiye — {offer} chal raha hai.") if offer else "",
        L(h, "One session this week is all it takes to restart the habit — the longer the gap, the harder the comeback.",
          "Is hafte bas ek session — gap jitna lamba, comeback utna mushkil.") if ctx.slug == "gyms" else "",
        slot_cta(ctx, h, ("book a comeback session this week", "is hafte comeback session book karein"), ("pause reminders", "reminders band karein"))[0],
    )
    return Draft(body, "binary", "Lapsed member win-back using days since last visit and prior goal.")


def trial_followup(ctx: Ctx) -> Draft | None:
    f, h = ctx.facts, cust_hinglish(ctx)
    child = customer_name(ctx) if customer_parent(ctx) else None
    trial = f.get("p_trial_date_date")
    who = child or L(h, "you", "aap")
    thanks = L(h, f"Thanks for bringing {child} to the trial class" if child else "Thanks for coming to the trial class",
               f"{child} ko trial class mein laane ke liye shukriya" if child else "Trial class ke liye shukriya")
    offer = f.get("active_offer")
    body = join(
        greeting(ctx),
        thanks + (f" on {trial}." if trial else "."),
        L(h, f"To keep going, {who} can join with our {offer}.", f"Aage continue karne ke liye {offer} hai.") if offer else "",
        L(h, "The first few weeks are where the habit sticks, so it's best not to break the rhythm now.",
          "Pehle kuch hafte mein hi aadat banti hai, isliye abhi rhythm mat todiye.") if ctx.slug == "gyms" else "",
        slot_cta(ctx, h, ("book the next session", "next session book karein"), ("ask a question first", "pehle ek sawaal"))[0],
    )
    return Draft(body, "binary", "Trial follow-up with the real next-session slot.")


def chronic_refill_due(ctx: Ctx) -> Draft | None:
    f, h = ctx.facts, cust_hinglish(ctx)
    mols = [v for k, v in sorted(f.items()) if re.fullmatch(r"p_molecule_list_\d+", k)]
    runs_out = f.get("p_stock_runs_out_iso_date")
    if not (mols or runs_out):
        return None
    if len(mols) > 1:
        mol_txt = ", ".join(mols[:-1]) + (" aur " if h else " and ") + mols[-1]
    else:
        mol_txt = mols[0] if mols else L(h, "regular medicines", "regular dawaiyan")
    last = f" (last refill {f['p_last_refill_date']})" if f.get("p_last_refill_date") else ""
    senior = bool(((ctx.customer or {}).get("identity") or {}).get("senior_citizen"))
    offer = matching_offer(ctx, "senior") if senior else None
    offer = offer or matching_offer(ctx, "delivery")
    delivery = ctx.payload.get("delivery_address_saved") is True
    body = join(
        greeting(ctx),
        L(h, f"Your {mol_txt} will run out by {runs_out}{last}." if runs_out else f"Your {mol_txt} refill is due{last}.",
          f"Aapki {mol_txt} ki dawai {runs_out} tak khatam ho jayegi{last}." if runs_out else f"Aapki {mol_txt} refill due hai{last}."),
        L(h, f"{offer} applies." if offer else "", f"{offer} bhi milega." if offer else ""),
        L(h, "Reply 1 for delivery to your saved address, or 2 to pick up at the store.",
          "Reply 1 — saved address pe delivery, ya 2 — store se pickup.") if delivery else
        L(h, "Reply 1 to have it packed for pickup, or 2 if you've already refilled.", "Reply 1 — pickup ke liye pack karein, ya 2 — already le li."),
    )
    return Draft(body, "binary", "Chronic refill timed off the stock run-out date in the payload.")


CUSTOMER_COMPOSERS: dict[str, Callable[[Ctx], Draft | None]] = {
    "recall_due": recall_due,
    "wedding_package_followup": wedding_package_followup,
    "customer_lapsed_hard": customer_lapsed_hard,
    "trial_followup": trial_followup,
    "chronic_refill_due": chronic_refill_due,
}
