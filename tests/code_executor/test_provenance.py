from code_executor.provenance import (
    flatten_document_sources,
    locate_result_sources_from_docjson,
)
from code_executor.document.models.document import Document


DOCJSON = {
    "pages": [{"number": 1, "bbox": [0, 0, 600, 800]}],
    "tree": {
        "root": {
            "id": 0,
            "type": "title",
            "parent_path": [],
            "page_number": 0,
            "data": {"text": "", "textlines": []},
            "children": [
                {
                    "id": 1,
                    "type": "title",
                    "parent_path": [],
                    "page_number": 1,
                    "data": {
                        "text": "测试公告",
                        "textlines": [
                            {
                                "text": "测试公告",
                                "page_number": 1,
                                "bbox": [10, 20, 110, 40],
                            }
                        ],
                    },
                    "children": [
                        {
                            "id": 2,
                            "type": "section",
                            "parent_path": [1],
                            "page_number": 1,
                            "data": {
                                "textlines": [
                                    {
                                        "text": "证券代码：301171",
                                        "page_number": 1,
                                        "bbox": [20, 60, 180, 80],
                                    }
                                ]
                            },
                            "children": [],
                        }
                    ],
                }
            ],
        }
    },
}


def test_flatten_document_sources_keeps_page_bbox_and_chapter_path():
    document = Document.from_dict(DOCJSON)

    sources = flatten_document_sources(document)

    assert any(
        source.text == "证券代码：301171"
        and source.page == 1
        and source.bbox == [20, 60, 180, 80]
        and source.chapter_path == ["测试公告"]
        for source in sources
    )


def test_locate_result_sources_from_docjson_exact_match():
    result = {"证券代码": "301171"}

    sources = locate_result_sources_from_docjson(result, DOCJSON)

    assert sources["证券代码"][0]["page"] == 1
    assert sources["证券代码"][0]["bbox"] == [20, 60, 180, 80]
    assert sources["证券代码"][0]["match_type"] == "exact"
