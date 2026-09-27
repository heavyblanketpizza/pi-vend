from django.db import models


class ApiCache(models.Model):
    """Raw API responses, cached per user to stay inside Naver's daily quotas."""

    scope = models.CharField(max_length=40, default="", db_index=True)
    kind = models.CharField(max_length=40)
    key = models.CharField(max_length=255)
    payload = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["scope", "kind", "key"], name="unique_api_cache_entry")]

    def __str__(self):
        return f"{self.kind}:{self.key}"


class KeywordStat(models.Model):
    """Latest 검색광고 키워드도구 numbers for one keyword.

    Every keywordstool call returns hundreds of related keywords; they're all
    upserted here so later lookups for any of them hit the cache. Rows are
    kept per user (scope), like ApiCache.
    """

    scope = models.CharField(max_length=40, default="")
    normalized = models.CharField(max_length=100)
    keyword = models.CharField(max_length=100)
    pc_searches = models.PositiveIntegerField(default=0)
    mobile_searches = models.PositiveIntegerField(default=0)
    pc_under_10 = models.BooleanField(default=False)
    mobile_under_10 = models.BooleanField(default=False)
    pc_clicks = models.FloatField(default=0)
    mobile_clicks = models.FloatField(default=0)
    pc_ctr = models.FloatField(default=0)
    mobile_ctr = models.FloatField(default=0)
    competition = models.CharField(max_length=10, blank=True)
    ad_depth = models.FloatField(default=0)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-mobile_searches"]
        constraints = [models.UniqueConstraint(fields=["scope", "normalized"], name="unique_keyword_stat")]

    def __str__(self):
        return self.keyword

    @property
    def total_searches(self) -> int:
        return self.pc_searches + self.mobile_searches

    def as_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "monthly_searches": {
                "pc": self.pc_searches,
                "mobile": self.mobile_searches,
                "total": self.total_searches,
                "pc_under_10": self.pc_under_10,
                "mobile_under_10": self.mobile_under_10,
            },
            "monthly_avg_clicks": {"pc": self.pc_clicks, "mobile": self.mobile_clicks},
            "ctr_percent": {"pc": self.pc_ctr, "mobile": self.mobile_ctr},
            "ad_competition": self.competition,
            "avg_ad_depth": self.ad_depth,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }
