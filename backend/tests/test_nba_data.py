from datetime import date
from unittest.mock import patch

from nba_wins_pool.nba_data import parse_schedule, parse_scoreboard, schedule_cache


@patch("nba_wins_pool.nba_data.request_helper")
def test_parse_schedule_cache(mock_request_helper):
    # Mock the response from the NBA schedule API
    mock_response = {
        "leagueSchedule": {
            "seasonYear": "2024-25",
            "leagueId": "00",
            "weeks": [{"startDate": "2023-10-01"}],
            "gameDates": [
                {
                    "gameDate": "2023-10-10",
                    "games": [
                        {
                            "gameDateTimeUTC": "2023-10-10T00:00:00Z",
                            "homeTeam": {"teamTricode": "LAL", "score": 100},
                            "awayTeam": {"teamTricode": "BOS", "score": 90},
                            "gameStatusText": "Final",
                            "gameStatus": 3,
                        }
                    ],
                }
            ],
        }
    }
    mock_request_helper.return_value = mock_response

    # Clear the cache before the test
    schedule_cache.clear()

    # Call parse_schedule for the first time
    scoreboard_date = date(2023, 10, 11)
    result_first_call = parse_schedule(scoreboard_date)

    # Check that the cache is set
    assert scoreboard_date in schedule_cache
    assert schedule_cache[scoreboard_date] == result_first_call

    # Call parse_schedule for the second time
    result_second_call = parse_schedule(scoreboard_date)

    # Check that the result is the same and the cache was used
    assert result_first_call == result_second_call
    assert result_first_call[1] == "2024-25"
    mock_request_helper.assert_called_once()  # Ensure the API was called only once


@patch("nba_wins_pool.nba_data.request_helper")
def test_parse_schedule_before_start_date(mock_request_helper):
    # Mock the response from the NBA schedule API
    mock_response = {
        "leagueSchedule": {
            "seasonYear": "2024-25",
            "leagueId": "00",
            "weeks": [{"startDate": "2023-10-01"}],
            "gameDates": [
                {
                    "gameDate": "2023-10-10",
                    "games": [
                        {
                            "gameDateTimeUTC": "2023-10-10T00:00:00Z",
                            "homeTeam": {"teamTricode": "LAL", "score": 100},
                            "awayTeam": {"teamTricode": "BOS", "score": 90},
                            "gameStatusText": "Final",
                            "gameStatus": 3,
                        }
                    ],
                }
            ],
        }
    }
    mock_request_helper.return_value = mock_response

    # Clear the cache before the test
    schedule_cache.clear()

    # Call parse_schedule with a date before the start date
    scoreboard_date = date(2023, 9, 30)
    result, _ = parse_schedule(scoreboard_date)

    # Check that the result is empty and the cache is set
    assert result == []
    assert scoreboard_date in schedule_cache
    assert schedule_cache[scoreboard_date][0] == result


@patch("nba_wins_pool.nba_data.request_helper")
def test_parse_scoreboard_empty_games(mock_request_helper):
    # Mock the response from the NBA schedule API with an empty list of games
    mock_response = {
        "scoreboard": {
            "gameDate": "2024-12-18",
            "leagueId": "00",
            "leagueName": "National Basketball Association",
            "games": [],
        }
    }
    mock_request_helper.return_value = mock_response
    result, scoreboard_date = parse_scoreboard()
    assert result == []
    assert scoreboard_date == date(2024, 12, 18)
