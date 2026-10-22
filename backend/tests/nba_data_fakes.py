"""Async methods that NbaDataService fakes share, delegating to the fakes' sync ones."""


class AsyncNbaDataMethods:
    async def get_current_season_async(self):
        return self.get_current_season()

    async def get_scoreboard_date_async(self, season):
        return self.get_scoreboard_date(season)

    async def get_live_checked_at(self, season):
        return None

    async def get_game_win_probabilities_async(self):
        odds = getattr(self, "get_sportsbook_game_win_probabilities", None)
        return odds() if odds else {}
