"""Read results carry each document's raw tag ids (spec D4).

A caller scoping searches by tag verifies the scope held from these ids, so
they are the raw ``documents.tag_ids`` values — not the name-resolved list —
and an id missing from the taxonomy is still reported. ``populated_db`` (from
``tests/unit/store/conftest.py``): document 1 carries tags 101 and 102,
document 2 carries tag 102.
"""

from __future__ import annotations

from store.models import DocumentBrowseQuery
from tests.helpers.factories import (
    make_chunk_input,
    make_document_meta,
    make_search_filters,
)
from tests.helpers.store import open_reader, open_writer

# A tag id the taxonomy does not name — placeholder, no real taxonomy id.
_UNNAMED_TAG = 999


def _browse_all() -> DocumentBrowseQuery:
    return DocumentBrowseQuery(
        text=None,
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
        sort="created",
        descending=True,
        offset=0,
        limit=20,
    )


def test_get_documents_carries_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        by_id = {doc.id: doc.tag_ids for doc in reader.get_documents([1, 2])}
    finally:
        reader.close()

    assert by_id == {1: (101, 102), 2: (102,)}


def test_get_document_summary_carries_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        summary = reader.get_document_summary(1)
    finally:
        reader.close()

    assert summary is not None
    assert summary.tag_ids == (101, 102)


def test_list_documents_carries_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        page = reader.list_documents(_browse_all())
    finally:
        reader.close()

    assert {doc.id: doc.tag_ids for doc in page.documents} == {
        1: (101, 102),
        2: (102,),
    }


def test_keyword_document_search_hits_carry_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        page = reader.keyword_document_search(("boiler",), make_search_filters(), 20, 0)
    finally:
        reader.close()

    assert [hit.document.tag_ids for hit in page.hits] == [(101, 102)]


def test_a_tag_id_missing_from_the_taxonomy_is_still_reported(
    populated_db: str,
) -> None:
    """The name list drops an unnamed tag; the id list must not."""
    writer = open_writer(populated_db)
    try:
        writer.upsert_document(
            make_document_meta(id=3, tag_ids=(_UNNAMED_TAG,), content_hash="hash3"),
            [make_chunk_input(dimensions=4)],
        )
    finally:
        writer.close()
    reader = open_reader(populated_db)
    try:
        (document,) = reader.get_documents([3])
    finally:
        reader.close()

    assert document.tags == ()
    assert document.tag_ids == (_UNNAMED_TAG,)
