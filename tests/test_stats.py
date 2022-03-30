from conftest import ac


def test_getNumCardsReviewedToday(setup):
    result = ac.getNumCardsReviewedToday()
    assert isinstance(result, int)


def test_getNumCardsReviewedByDay(setup):
    result = ac.getNumCardsReviewedByDay()
    assert isinstance(result, list)


def test_getCollectionStatsHTML(setup):
    result = ac.getCollectionStatsHTML()
    assert isinstance(result, str)


class TestReviews:
    def test_zero_reviews_for_a_new_deck(self, setup):
        assert ac.cardReviews(deck="test_deck", startID=0) == []
        assert ac.getLatestReviewID(deck="test_deck") == 0

    def test_some_reviews_for_a_reviewed_deck(self, setup):
        ac.insertReviews(reviews=[
            (456, setup.card_ids[0], -1, 3, 4, -60, 2500, 6157, 0),
            (789, setup.card_ids[1], -1, 1, -60, -60, 0, 4846, 0)
        ])

        assert len(ac.cardReviews(deck="test_deck", startID=0)) == 2
        assert ac.getLatestReviewID(deck="test_deck") == 789
