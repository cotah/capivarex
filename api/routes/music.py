"""
api/routes/music.py
====================
REST API routes for Spotify music integration.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_spotify():
    """Lazy-load SpotifyService with guard."""
    from services import get_service

    svc = get_service("spotify")
    if not svc:
        raise HTTPException(
            status_code=503,
            detail="Spotify service unavailable",
        )
    return svc


@router.get("/search")
async def search_music(
    q: str = Query(..., description="Search query"),
    type: str = Query(
        "track",
        description=("Search type: track, artist, album, playlist"),
    ),
    limit: int = Query(5, ge=1, le=20),
):
    """Search Spotify for tracks, artists, albums."""
    spotify = _get_spotify()

    if not spotify.is_initialized():
        await spotify.initialize()

    try:
        results = await spotify.search(
            query=q,
            search_type=type,
            limit=limit,
        )
        return {
            "results": results,
            "query": q,
            "type": type,
        }
    except Exception as e:
        logger.error("Spotify search failed: %s", e)
        raise HTTPException(status_code=500, detail="Search failed")


@router.get("/track/{track_id}")
async def get_track(track_id: str):
    """Get track details by Spotify ID."""
    spotify = _get_spotify()

    if not spotify.is_initialized():
        await spotify.initialize()

    try:
        return await spotify.get_track(track_id)
    except Exception as e:
        logger.error(
            "Failed to get track %s: %s",
            track_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to get track",
        )


@router.get("/artist/{artist_id}")
async def get_artist(artist_id: str):
    """Get artist details by Spotify ID."""
    spotify = _get_spotify()

    if not spotify.is_initialized():
        await spotify.initialize()

    try:
        return await spotify.get_artist(artist_id)
    except Exception as e:
        logger.error(
            "Failed to get artist %s: %s",
            artist_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to get artist",
        )


@router.get("/artist/top-tracks")
async def get_artist_top_tracks(
    name: str = Query(..., description="Artist name"),
    limit: int = Query(10, ge=1, le=20),
):
    """Get top tracks for an artist (search-based)."""
    spotify = _get_spotify()

    if not spotify.is_initialized():
        await spotify.initialize()

    try:
        tracks = await spotify.get_artist_top_tracks(name, limit=limit)
        return {"tracks": tracks, "artist": name}
    except Exception as e:
        logger.error(
            "Failed to get top tracks for %s: %s",
            name,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to get top tracks",
        )


@router.get("/recommendations")
async def get_recommendations(
    genres: str = Query(
        None,
        description="Comma-separated genre seeds",
    ),
    artists: str = Query(
        None,
        description="Comma-separated artist names",
    ),
    limit: int = Query(5, ge=1, le=20),
):
    """Get music recommendations (search-based)."""
    spotify = _get_spotify()

    if not spotify.is_initialized():
        await spotify.initialize()

    try:
        seed_genres = genres.split(",") if genres else None
        seed_artists = artists.split(",") if artists else None
        results = await spotify.get_recommendations(
            seed_genres=seed_genres,
            seed_artists=seed_artists,
            limit=limit,
        )
        return {"recommendations": results}
    except Exception as e:
        logger.error("Recommendations failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Recommendations failed",
        )
