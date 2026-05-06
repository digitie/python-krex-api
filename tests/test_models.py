import pytest

from kex_openapi import CoordinateSystem, GeoPoint, Page, RawCoordinate


def test_page_behaves_like_read_only_sequence() -> None:
    page = Page(items=("a", "b"), total_count=2)

    assert list(page) == ["a", "b"]
    assert len(page) == 2
    assert page
    assert page.first == "a"
    assert page.is_empty is False


def test_empty_page_helpers() -> None:
    page: Page[str] = Page(items=())

    assert list(page) == []
    assert len(page) == 0
    assert not page
    assert page.first is None
    assert page.is_empty is True


def test_geo_point_standardizes_lon_lat_and_aliases() -> None:
    point = GeoPoint(lon=127.104, lat=37.332)

    assert point.lonlat == (127.104, 37.332)
    assert point.latlon == (37.332, 127.104)
    assert point.as_geojson_position() == (127.104, 37.332)
    assert point.longitude == point.lon
    assert point.latitude == point.lat


def test_geo_point_validates_ranges() -> None:
    with pytest.raises(ValueError):
        GeoPoint(lon=181, lat=37)
    with pytest.raises(ValueError):
        GeoPoint(lon=127, lat=91)


def test_raw_coordinate_defaults_to_unknown_system() -> None:
    coord = RawCoordinate(x=1, y=2)

    assert coord.system is CoordinateSystem.UNKNOWN
