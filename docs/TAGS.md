# Card tags

Spellbinder tags are administrator-defined labels attached to Oracle card
identities. A tag therefore applies to every owned printing of the same card.

Administrators create colored tag definitions from the Collection filter panel.
Authenticated administrators and shared-link guests can add or remove existing
tags from a card's detail view. Guests cannot create or delete tag definitions.
All tag mutations made through native sessions require the session CSRF token.

The Collection filter supports matching any selected tag, matching all selected
tags, or showing only untagged cards. The **Show Tags** preference controls tag
chips on collection cards and is saved in that browser.

Tag definitions and Oracle-card assignments are included in portable collection
backups. Schema migration 15 adds the `tags` and `card_tags` tables without
rebuilding collection or deck tables.

## Tag workflow page

The authenticated **Tags** page is available to administrators and guests. It
uses OR matching when more than one tag is checked, presents cards with the same
Name, Quantity, and Set/number sorting as Collection, and lets a user check off
physical cards while gathering them. **Untag Selected** atomically removes all
currently selected tags from every checked card; unrelated tags remain assigned.
