import pytest

from app.services import detect


@pytest.mark.parametrize("url,service,post_id,kind,norm", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL123&si=abc", "youtube", "jNQXAC9IVRw", "video",
     "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("https://youtu.be/jNQXAC9IVRw?si=xyz", "youtube", "jNQXAC9IVRw", "video",
     "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("https://www.youtube.com/shorts/aqz-KE-bpKQ", "youtube", "aqz-KE-bpKQ", "short",
     "https://www.youtube.com/watch?v=aqz-KE-bpKQ"),
    ("https://m.youtube.com/watch?v=jNQXAC9IVRw&t=10", "youtube", "jNQXAC9IVRw", "video",
     "https://www.youtube.com/watch?v=jNQXAC9IVRw&t=10"),
    ("https://music.youtube.com/watch?v=jNQXAC9IVRw&feature=share", "youtube", "jNQXAC9IVRw", "video",
     "https://music.youtube.com/watch?v=jNQXAC9IVRw"),
    ("https://www.youtube.com/playlist?list=PLx", "youtube", None, "playlist",
     "https://www.youtube.com/playlist?list=PLx"),
    ("https://www.instagram.com/reel/C1a2b3c4d5e/?igsh=MWQ1ZGUxMzBkMA==", "instagram", "C1a2b3c4d5e", "reel",
     "https://www.instagram.com/reel/C1a2b3c4d5e/"),
    ("https://www.instagram.com/reels/C1a2b3c4d5e/", "instagram", "C1a2b3c4d5e", "reel",
     "https://www.instagram.com/reel/C1a2b3c4d5e/"),
    ("https://instagram.com/p/BoHk1haB5tM/?img_index=2", "instagram", "BoHk1haB5tM", "post",
     "https://www.instagram.com/p/BoHk1haB5tM/"),
    ("https://www.instagram.com/someone/p/BoHk1haB5tM/", "instagram", "BoHk1haB5tM", "post",
     "https://www.instagram.com/p/BoHk1haB5tM/"),
    ("https://www.ddinstagram.com/reel/C1a2b3c4d5e/", "instagram", "C1a2b3c4d5e", "reel",
     "https://www.instagram.com/reel/C1a2b3c4d5e/"),
    ("https://www.instagram.com/share/reel/BAmwNz0rY/", "instagram", "BAmwNz0rY", "share", None),
    ("https://www.instagram.com/stories/natgeo/3456789012345678901/", "instagram", "3456789012345678901", "story",
     "https://www.instagram.com/stories/natgeo/3456789012345678901/"),
    ("https://x.com/perrypumas/status/894001459754180609?s=20", "twitter", "894001459754180609", "tweet",
     "https://x.com/perrypumas/status/894001459754180609"),
    ("https://twitter.com/i/web/status/1170041925560258560", "twitter", "1170041925560258560", "tweet",
     "https://x.com/i/status/1170041925560258560"),
    ("https://mobile.twitter.com/NASA/status/1065692031626829824/photo/1", "twitter", "1065692031626829824", "tweet",
     "https://x.com/NASA/status/1065692031626829824"),
    ("https://fxtwitter.com/user/status/123456789", "twitter", "123456789", "tweet",
     "https://x.com/user/status/123456789"),
    ("https://vxtwitter.com/i/status/123456789", "twitter", "123456789", "tweet",
     "https://x.com/i/status/123456789"),
    ("https://www.tiktok.com/@chillezy/photo/7240568259186019630?is_from_webapp=1", "tiktok",
     "7240568259186019630", "photo", "https://www.tiktok.com/@chillezy/photo/7240568259186019630"),
    ("https://www.tiktok.com/@leenabhushan/video/6748451240264420610", "tiktok", "6748451240264420610", "video",
     "https://www.tiktok.com/@leenabhushan/video/6748451240264420610"),
    ("https://www.tiktokv.com/share/video/7240568259186019630", "tiktok", "7240568259186019630", "video",
     "https://www.tiktok.com/@i/video/7240568259186019630"),
    ("https://m.tiktok.com/v/6748451240264420610.html", "tiktok", "6748451240264420610", "video",
     "https://www.tiktok.com/@i/video/6748451240264420610"),
    ("https://vm.tiktok.com/ZMabcdef/", "tiktok", None, "short", None),
    ("https://www.tiktok.com/t/ZTRabcdef/", "tiktok", None, "short", None),
    ("https://www.reddit.com/r/videos/comments/abc/title/", "generic", None, None, None),
])
def test_detect(url, service, post_id, kind, norm):
    m = detect(url)
    assert m.service == service
    assert m.post_id == post_id
    assert m.kind == kind
    if norm:
        assert m.url == norm
