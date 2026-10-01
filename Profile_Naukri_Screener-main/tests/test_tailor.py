"""naukri/jobs/tailor.py: the resume sent with a company-site application."""
import copy

import pytest

from naukri.jobs import tailor as T


@pytest.fixture(scope="module")
def vocab():
    return T._vocab()


RESUME = {
    "name": "A B", "title": "Backend Software Engineer | Java, Kafka",
    "summary": "Engineer with **2 years** on Kafka.",
    "skills": [{"label": "Backend", "items": "Spring Boot, REST APIs, Microservices"},
               {"label": "Languages", "items": "Java, SQL, HTML5"},
               {"label": "Spoken", "items": "English"}],
    "extra_skills": [{"label": "Languages", "items": "Python"}, {"label": "Tools", "items": "Git"}],
    "experience": [{"title": "Software Engineer", "org": "X", "dates": "2024 - now",
                    "bullets": [f"Did thing {i} with Kafka" if i % 2 else f"Did thing {i}" for i in range(9)]}],
    "projects": [{"name": "P", "year": "2025", "tech": "React", "bullets": ["one", "two", "three with Java"]}],
}


def test_headline_takes_the_job_title_only_when_it_is_honestly_yours(vocab):
    have = set(vocab.find("java spring boot rest api kafka"))
    own = RESUME["title"]
    assert T.headline_role("Software Engineer II - R01570649 (Java)", own, have, vocab) == "Software Engineer"
    assert T.headline_role("Java Developer", own, have, vocab) == "Java Developer"
    for title in ("Software Development Lead - R01570649", "PHP Full Stack Developer", "Automation Test Engineer",
                  "Senior Backend Engineer", "Deployment Engineer"):
        assert T.headline_role(title, own, have, vocab) == "Backend Software Engineer", title


def test_job_words_are_added_next_to_the_skill_you_have(vocab):
    new = copy.deepcopy(RESUME)
    terms = T.jd_terms("We build RESTful services in Java.", vocab)
    added = T._use_job_words(new, terms, ["rest api", "java"], vocab)
    assert added == ["RESTful"]
    assert "REST APIs (RESTful)" in new["skills"][0]["items"]
    assert new["skills"][1]["items"] == "Java, SQL, HTML5"         # "Java" was already the job's word


def test_extra_skills_are_added_only_when_the_job_asks(vocab):
    new = copy.deepcopy(RESUME)
    assert T._add_extras(new, set(vocab.find("python and kafka")), vocab) == ["Python"]
    assert new["skills"][1]["items"] == "Java, SQL, HTML5, Python"
    assert all("Git" not in g["items"] for g in new["skills"])


def test_fitting_one_page_never_strips_a_role_bare(vocab):
    new = copy.deepcopy(RESUME)
    while T._drop_least_relevant(new, ["kafka", "java"], vocab):
        pass
    assert len(new["experience"][0]["bullets"]) == T.MIN_BULLETS["experience"]
    assert len(new["projects"][0]["bullets"]) == T.MIN_BULLETS["projects"]
    assert "three with Java" in new["projects"][0]["bullets"]       # the bullet the job cares about stays
    assert sum("Kafka" in b for b in new["experience"][0]["bullets"]) == 4


def test_html5_counts_as_html(vocab):
    assert "html" in vocab.find("HTML5, CSS3") and "css" in vocab.find("HTML5, CSS3")


def test_pdf_layout_keeps_text_and_links():
    br = T._resume_module()
    page = br.to_html({**RESUME, "contact": ["City | 123"], "links": [{"text": "github", "url": "https://github.com/x"}],
                       "education": [{"degree": "B.Tech", "institution": "U", "years": "2021 - 2025", "grade": "CGPA: 8"}],
                       "certifications": ["**Cert** - text"]})
    assert '<a href="https://github.com/x">github</a>' in page
    assert "<b>2 years</b>" in page and "<b>Cert</b> - text" in page
    assert page.index("Education") < page.index("Certifications")
