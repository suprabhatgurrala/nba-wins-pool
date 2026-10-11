import os
from pathlib import PurePosixPath
from typing import Any

from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope


# https://stackoverflow.com/questions/63069190/how-to-capture-arbitrary-paths-at-one-route-in-fastapi
class SinglePageApplication(StaticFiles):
    def __init__(self, directory: os.PathLike, index="index.html") -> None:
        self.index = index

        # set html=True to resolve the index even when no
        # the base path is passed in
        super().__init__(directory=directory, packages=None, html=True, check_dir=True)

    def lookup_path(self, path: str):
        full_path, stat_result = super().lookup_path(path)

        # Only fall back to the SPA shell for extensionless routes; missing static
        # assets (e.g. /assets/*.js) should 404, not silently return HTML.
        if stat_result is None and "." not in PurePosixPath(path).name:
            return super().lookup_path(self.index)

        return (full_path, stat_result)

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        # Never cache the SPA shell; it references content-hashed asset filenames that change per deploy.
        if os.path.basename(str(full_path)) == self.index:
            response.headers["Cache-Control"] = "no-cache"
        return response
