import json

from app.extractors import gallerydl, instagram, tiktok, twitter, ytdlp
from app.services import detect


# --- yt-dlp ---------------------------------------------------------------------

def _fmt(fid, ext, vcodec, acodec, h=None):
    return {"format_id": fid, "ext": ext, "vcodec": vcodec, "acodec": acodec, "height": h,
            "url": f"https://cdn.example/{fid}.{ext}"}


def test_ytdlp_instagram_carousel_keeps_photos_in_order():
    data = {
        "_type": "playlist", "id": "BoHk1haB5tM", "title": "Post by instagram", "channel": "instagram",
        "webpage_url": "https://www.instagram.com/p/BoHk1haB5tM/",
        "entries": [
            {"id": "1", "title": "Video by instagram", "formats": [], "thumbnails": [
                {"url": "https://scontent.cdninstagram.com/small.jpg", "width": 150, "height": 150},
                {"url": "https://scontent.cdninstagram.com/big.jpg", "width": 1080, "height": 1080}]},
            {"id": "2", "title": "Video by instagram", "duration": 12.5,
             "formats": [_fmt("dash-v", "mp4", "avc1", "none", 1920), _fmt("dash-a", "m4a", "none", "mp4a")],
             "thumbnails": [{"url": "https://scontent.cdninstagram.com/vthumb.jpg"}]},
            None,
        ],
    }
    res = ytdlp.parse_info(data, detect("https://www.instagram.com/p/BoHk1haB5tM/"))
    assert res.ok
    assert [i.type for i in res.items] == ["photo", "video"]
    photo, video = res.items
    assert photo.url == "https://scontent.cdninstagram.com/big.jpg"
    assert photo.source == "direct" and photo.headers["Referer"] == "https://www.instagram.com/"
    assert video.source == "ytdlp" and video.playlist_index == 2 and video.has_audio is True
    assert video.page_url == "https://www.instagram.com/p/BoHk1haB5tM/"


def test_ytdlp_no_formats_outside_instagram_is_empty():
    data = {"id": "1", "title": "t", "formats": [], "thumbnails": [{"url": "https://x/t.jpg"}]}
    res = ytdlp.parse_info(data, detect("https://x.com/a/status/1"))
    assert not res.ok and res.error == "content.empty"


def test_ytdlp_strips_heavy_fields_and_detects_audio():
    data = {"id": "abc", "title": "song", "uploader": "artist", "duration": 200,
            "formats": [_fmt("251", "webm", "none", "opus")], "automatic_captions": {"en": [1] * 1000},
            "webpage_url": "https://soundcloud.com/a/b"}
    res = ytdlp.parse_info(data, detect("https://soundcloud.com/a/b"))
    item = res.items[0]
    assert item.type == "audio" and "automatic_captions" not in item.info
    assert res.author == "artist" and item.page_url == "https://soundcloud.com/a/b"


def test_ytdlp_live_is_reported():
    data = {"id": "x", "title": "live", "is_live": True, "formats": [_fmt("1", "mp4", "avc1", "aac")]}
    res = ytdlp.parse_info(data, detect("https://www.youtube.com/watch?v=jNQXAC9IVRw"))
    assert res.error == "content.live"


def test_ytdlp_flat_playlist_entries_are_lazy():
    data = {"_type": "playlist", "title": "pl", "entries": [
        {"_type": "url", "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "A", "duration": 10}]}
    res = ytdlp.parse_info(data, detect("https://www.youtube.com/playlist?list=PL"))
    assert res.items[0].page_url.endswith("aaaaaaaaaaa") and res.items[0].info is None


# --- gallery-dl -------------------------------------------------------------------

def test_gallerydl_tiktok_slideshow():
    kw = {"category": "tiktok", "post_type": "image", "desc": "mon diapo", "author": {"uniqueId": "chillezy"}}
    messages = [
        [2, kw],
        [3, "https://p16-sign.tiktokcdn.com/a.jpeg?x=1", {**kw, "extension": "jpeg", "num": 1}],
        [3, "https://p16-sign.tiktokcdn.com/b.jpeg?x=1", {**kw, "extension": "jpeg", "num": 2}],
        [3, "https://sf16.tiktokcdn.com/music.mp3", {**kw, "extension": "mp3", "num": 0}],
    ]
    res = gallerydl.parse_messages(messages, "https://www.tiktok.com/@chillezy/photo/1")
    assert [i.type for i in res.items] == ["photo", "photo"]
    assert res.audio and res.audio.ext == "mp3"
    assert res.title == "mon diapo" and res.author == "chillezy"
    assert res.items[0].headers["Referer"] == "https://www.tiktok.com/"


def test_gallerydl_ytdl_delegation_and_errors():
    res = gallerydl.parse_messages([[3, "ytdl:https://www.tiktok.com/@a/video/1", {"extension": "mp4"}]],
                                   "https://www.tiktok.com/@a/video/1")
    assert res.items[0].source == "ytdlp" and res.items[0].page_url.endswith("/video/1")
    err = gallerydl.parse_messages([[-1, {"error": "AuthorizationError", "message": "Login required"}]],
                                   "https://www.instagram.com/p/x/")
    assert err.error == "content.login"


# --- X / Twitter ------------------------------------------------------------------

SYNDICATION = {
    "__typename": "Tweet", "text": "4 images https://t.co/abc", "user": {"screen_name": "perrypumas"},
    "mediaDetails": [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/DGbb.jpg",
         "original_info": {"width": 1200, "height": 800}},
        {"type": "video", "media_url_https": "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/t.jpg",
         "video_info": {"duration_millis": 8000, "variants": [
             {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/a.m3u8"},
             {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/480.mp4"},
             {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/720.mp4"}]}},
        {"type": "animated_gif", "media_url_https": "https://pbs.twimg.com/tweet_video_thumb/g.jpg",
         "video_info": {"variants": [{"content_type": "video/mp4", "bitrate": 0,
                                      "url": "https://video.twimg.com/tweet_video/g.mp4"}]}},
    ],
}


def test_twitter_syndication_mixed_media():
    res = twitter.parse_syndication(SYNDICATION, "894001459754180609")
    assert [i.type for i in res.items] == ["photo", "video", "gif"]
    assert res.items[0].url == "https://pbs.twimg.com/media/DGbb?format=jpg&name=orig"
    assert res.items[1].url == "https://video.twimg.com/720.mp4" and res.items[1].duration == 8
    assert res.author == "perrypumas"


def test_twitter_tombstone():
    assert twitter.parse_syndication({"__typename": "TweetTombstone"}, "1").error == "content.unavailable"


def test_twitter_fxtwitter():
    data = {"code": 200, "tweet": {"text": "hello", "author": {"screen_name": "nasa"}, "media": {"all": [
        {"type": "photo", "url": "https://pbs.twimg.com/media/X.jpg", "width": 10, "height": 10},
        {"type": "video", "url": "https://video.twimg.com/v.mp4", "thumbnail_url": "https://pbs.twimg.com/t.jpg",
         "duration": 3.2}]}}}
    res = twitter.parse_fxtwitter(data, "1")
    assert [i.type for i in res.items] == ["photo", "video"]
    assert res.items[0].url.endswith("name=orig")


def test_twitter_token_matches_javascript():
    # valeurs calculées avec Node.js : ((id / 1e15) * Math.PI).toString(36).replace(/(0+|\.)/g, '')
    assert twitter.syndication_token("20") == "6dq1a2xwd93"
    assert twitter.syndication_token("894001459754180609") == "26l6l8q7is"
    assert twitter.syndication_token("1839019491835129889") == "4ghg7d1r3kv"
    assert twitter.js_to_radix(0.5, 36) == "0.i"
    assert twitter.js_to_radix(1e21, 36) == "5v1j4f4ds7c000"


# --- TikTok -----------------------------------------------------------------------

def _tiktok_html(item: dict, status: int = 0) -> str:
    payload = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": status, "statusMsg": "",
                                                            "itemInfo": {"itemStruct": item}}}}
    return ('<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            + json.dumps(payload) + "</script></html>")


def test_tiktok_slideshow():
    item = {"id": "7240568259186019630", "desc": "photos", "author": {"uniqueId": "chillezy"},
            "imagePost": {"images": [
                {"imageURL": {"urlList": ["https://p16.tiktokcdn.com/a.webp?x", "https://p16.tiktokcdn.com/a.jpeg?x"]},
                 "imageWidth": 1080, "imageHeight": 1920},
                {"imageURL": {"urlList": ["https://p16.tiktokcdn.com/b.jpeg?x"]}}]},
            "music": {"playUrl": "https://sf16.tiktokcdn.com/obj/music.mp3", "title": "son original", "duration": 30},
            "video": {"playAddr": ""}}
    found, err = tiktok.find_item_struct(_tiktok_html(item))
    assert err is None
    res = tiktok.parse_item(found, "7240568259186019630", "tt_chain_token=abc")
    assert [i.type for i in res.items] == ["photo", "photo"]
    assert res.items[0].url == "https://p16.tiktokcdn.com/a.jpeg?x"
    assert res.audio and res.audio.ext == "mp3" and res.audio.title == "son original"
    assert res.items[0].headers["Cookie"] == "tt_chain_token=abc"


def test_tiktok_video_prefers_h264_variant():
    item = {"id": "1", "desc": "vid", "author": {"uniqueId": "u"}, "video": {
        "playAddr": "https://v16.tiktokcdn.com/play.mp4", "cover": "https://p16/c.jpg", "duration": 15,
        "bitrateInfo": [
            {"CodecType": "h265_hvc1", "Bitrate": 2000000, "PlayAddr": {"UrlList": ["https://v/h265.mp4"]}},
            {"CodecType": "h264", "Bitrate": 1500000, "PlayAddr": {"UrlList": ["https://v/h264.mp4"]}}]},
        "music": {"playUrl": "https://m/m.mp3"}}
    res = tiktok.parse_item(item, "1", "")
    item = res.items[0]
    assert item.type == "video" and item.url == "https://v16.tiktokcdn.com/play.mp4"
    assert item.fallback_urls == ["https://v/h264.mp4", "https://v/h265.mp4"]
    assert item.page_url == "https://www.tiktok.com/@u/video/1"
    assert "Cookie" not in res.items[0].headers


def test_tiktok_errors():
    assert tiktok.find_item_struct(_tiktok_html({}, status=10204))[1] == "content.unavailable"
    assert tiktok.find_item_struct("<html>captcha</html>")[1] == "fetch.fail"
    assert tiktok.parse_item({"isContentClassified": True}, "1", "").error == "content.age"


# --- Instagram --------------------------------------------------------------------

def test_instagram_shortcode_to_media_id():
    assert instagram.shortcode_to_media_id("BqvsDleB3lV") == "1922949326347663701"
    assert instagram.shortcode_to_media_id("BoHk1haB5tM") == "1875629777499953996"


def test_instagram_mobile_carousel():
    data = {"user": {"username": "instagram"}, "caption": {"text": "légende"}, "carousel_media": [
        {"image_versions2": {"candidates": [{"url": "https://ig/small.jpg", "width": 320, "height": 320},
                                            {"url": "https://ig/big.jpg", "width": 1080, "height": 1080}]}},
        {"image_versions2": {"candidates": [{"url": "https://ig/vthumb.jpg", "width": 640, "height": 640}]},
         "video_versions": [{"url": "https://ig/low.mp4", "width": 480, "height": 480},
                            {"url": "https://ig/high.mp4", "width": 1080, "height": 1080}],
         "video_duration": 9.1}]}
    res = instagram.parse_mobile_item(data, "BoHk1haB5tM")
    assert [i.type for i in res.items] == ["photo", "video"]
    assert res.items[0].url == "https://ig/big.jpg" and res.items[1].url == "https://ig/high.mp4"
    assert res.items[1].thumbnail == "https://ig/vthumb.jpg" and res.title == "légende"


def test_instagram_gql_sidecar_and_embed():
    media = {"owner": {"username": "instagram"},
             "edge_media_to_caption": {"edges": [{"node": {"text": "cap"}}]},
             "edge_sidecar_to_children": {"edges": [
                 {"node": {"display_url": "https://ig/1.jpg", "dimensions": {"width": 1, "height": 1}}},
                 {"node": {"is_video": True, "video_url": "https://ig/2.mp4", "display_url": "https://ig/2.jpg"}}]}}
    res = instagram.parse_gql_media(media, "X")
    assert [i.type for i in res.items] == ["photo", "video"] and res.author == "instagram"

    context = json.dumps({"gql_data": {"shortcode_media": media}})
    html = 'xx["init",[],[' + json.dumps({"contextJSON": context}) + ']],yy'
    assert instagram.parse_embed_html(html) == media
