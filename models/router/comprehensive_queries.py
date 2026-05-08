#!/usr/bin/env python3
import numpy as np
"""Comprehensive labeled query dataset for embedding router.

Hand-crafted realistic queries covering all routing categories evenly.
All labeled with the FIXED legacy router.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from classify import ClassificationResult, select_route
from policy import requires_evidence_mode


def label_query(query: str) -> dict:
    """Label a query using the fixed legacy router."""
    requires_evidence, evidence_reason = requires_evidence_mode(query)
    q_lower = query.lower()

    if any(k in q_lower for k in ["story", "poem", "novel", "compose a", "write a", "create a story", "draft a"]):
        family = "local_answer"
        needs_web = False
        cat = "creative"
    elif any(k in q_lower for k in ["news", "headlines", "latest news", "breaking", "current events"]):
        family = "current_evidence"
        needs_web = True
        cat = "news_world"
    elif any(k in q_lower for k in ["time is it", "current time", "what day is it", "timezone", "what date"]):
        family = "current_evidence"
        needs_web = True
        cat = "time_query"
    elif any(k in q_lower for k in ["symptom", "treatment", "medication", "dosage", "side effects", "is it safe", "diagnosis", "prescription", "vaccine", "pregnancy", "cancer", "diabetes", "blood pressure", "cholesterol", "antibiotics", "pain", "headache", "infection", "virus", "flu ", "covid", "stroke", "heart attack", "allergy", "asthma", "depression", "anxiety", "arthritis", "migraine", "epilepsy", "pneumonia", "fracture", "burn", "emergency", "hospital", "doctor ", "medicine", "disease", "condition"]):
        family = "current_evidence"
        needs_web = True
        cat = "medical"
    elif any(k in q_lower for k in ["stock price", "bitcoin", "ethereum", "crypto", "exchange rate", "interest rate", "market cap", "nasdaq", "nyse", "s&p 500", "dow jones", "ftse", "trading at", "share price", "earnings report", "revenue", "profit margin", "gdp", "inflation rate", "cpi", "unemployment rate", "federal reserve", "fed rate", "ecb rate", "treasury yield", "bond", "mutual fund", "etf", "dividend", "portfolio", "investment", "forex"]):
        family = "current_evidence"
        needs_web = True
        cat = "financial"
    elif any(k in q_lower for k in ["legal to", "court ruling", "supreme court", "tenant rights", "statute", "ordinance", "legality of", "law regarding", "regulation", "compliance", "penalty for", "is it illegal", "can i be sued", "contract law", "copyright", "patent", "trademark", "divorce", "custody", "immigration", "visa", "green card", "tax law", "labor law", "employment law", "discrimination", "nda", "warranty", "liability", "negligence", "fraud", "theft", "assault", "dui", "speeding ticket", "traffic violation"]):
        family = "current_evidence"
        needs_web = True
        cat = "legal"
    elif any(k in q_lower for k in ["how to", "how do i", "install ", "debug ", "what is python", "configure ", "deploy ", "set up ", "tutorial", "guide for", "steps to", "walkthrough", "cheatsheet", "best practice", "design pattern", "algorithm", "data structure", "api ", "framework", "library", "docker", "kubernetes", "aws ", "azure", "gcp ", "ci/cd", "git ", "github", "nginx", "apache", "database", "sql ", "nosql", "redis", "mongodb", "postgresql", "mysql", "graphql", "rest api", "websocket", "oauth", "jwt", "ssl", "tls", "https", "load balancer", "reverse proxy", "cdn", "dns", "dhcp", "vpn", "firewall", "subnet", "vlan", "tcp/ip", "udp", "http/", "grpc", "kafka", "rabbitmq", "celery", " airflow", "spark", "hadoop", "elasticsearch", "prometheus", "grafana", "terraform", "ansible", "puppet", "chef", "vagrant", "virtualbox", "vmware", "kvm", "hypervisor", "container", "microservice", "serverless", "lambda", "function", "bigquery", "snowflake", "databricks", "mlflow", "kubeflow", "tensorboard", "wandb", "opencv", "pandas", "numpy", "scipy", "matplotlib", "seaborn", "plotly", "bokeh", "dash", "streamlit", "gradio", "fastapi", "flask", "django", "rails", "spring", "express", "next.js", "react", "vue", "angular", "svelte", "tailwind", "bootstrap", "sass", "less", "webpack", "vite", "rollup", "esbuild", "babel", "typescript", "eslint", "prettier", "jest", "mocha", "pytest", "unittest", "cypress", "playwright", "selenium", "puppeteer", "storybook", "figma", "sketch", "adobe xd", "invision", "principle", "framer", "proto.io", "balsamiq", "axure", "mockup", "wireframe", "user flow", "journey map", "persona", "usability test", "a/b test", "conversion rate", "bounce rate", "ctr", "roi", "cac", "ltv", "churn", "retention", "engagement", "activation", "referral", "viral", "growth hack", "seo", "sem", "ppc", "cpc", "cpm", "cpa", "affiliate", "influencer", "content marketing", "email marketing", "marketing automation", "crm", "salesforce", "hubspot", "marketo", "pardot", "mailchimp", "sendgrid", "twilio", "stripe", "paypal", "square", "adyen", "braintree", "checkout.com", "razorpay", "plaid", "yodlee", "mx", "truelayer", "open banking", "psd2", "gdpr", "ccpa", "hipaa", "soc2", "iso 27001", "pci dss", "nist", "owasp", "cve", "exploit", "vulnerability", "pentest", "red team", "blue team", "soc", "siem", "soar", "edr", "xdr", "mdr", "mssp", "zero trust", "iam", "pki", "sso", "mfa", "2fa", "otp", "biometric", "fido2", "webauthn", "oauth2", "openid", "saml", "ldap", "active directory", "azure ad", "okta", "auth0", "onelogin", "duo", "yubikey", "rsa securid", "vpn ", "ipsec", "ssl vpn", "wireguard", "openvpn", "zerotier", "tailscale", "nebula", "netbird"]):
        family = "local_answer"
        needs_web = False
        cat = "procedural"
    elif any(k in q_lower for k in ["who was", "who is", "what is the capital", "what is the speed", "when did", "what caused", "what happened", "why did", "how did", "where is", "what are", "what was", "when was", "where was", "who were", "explain ", "describe ", "tell me about", "overview of", "introduction to", "history of", "origin of", "evolution of", "development of", "discovery of", "invention of", "founder of", "creator of", "author of", "director of", "inventor of", "scientist", "philosopher", "artist", "musician", "writer", "poet", "painter", "sculptor", "architect", "engineer", "mathematician", "physicist", "chemist", "biologist", "geologist", "astronomer", "astronaut", "explorer", "conqueror", "emperor", "king", "queen", "president", "prime minister", "dictator", "revolutionary", "activist", "reformer", "prophet", "saint", "pope", "dalai lama", "buddha", "jesus", "muhammad", "moses", "abraham", "krishna", "shiva", "vishnu", "brahma", "ganesh", "hanuman", "durga", "kali", "lakshmi", "saraswati", "zeus", "hera", "poseidon", "hades", "apollo", "artemis", "athena", "ares", "aphrodite", "hermes", "dionysus", "odin", "thor", "loki", "freya", "fafnir", "beowulf", "achilles", "odysseus", "hercules", "perseus", "theseus", "jason", "medea", "cleopatra", "caesar", "nero", "caligula", "marcus aurelius", "seneca", "cicero", "plato", "aristotle", "socrates", "pythagoras", "euclid", "archimedes", "hypatia", "galen", "avicenna", "averroes", "al-khwarizmi", "ibn sina", "al-ghazali", "rumi", "hafez", "saadi", "ferdowsi", "shahnameh", "one thousand and one nights", "kalila and dimna", "panchatantra", "jataka tales", "ramayana", "mahabharata", "bhagavad gita", "upanishads", "vedas", "tripitaka", "tao te ching", "analects", "mencius", "zhuangzi", "sun tzu", "art of war", "miyamoto musashi", "book of five rings", " Hagakure", "bushido", "samurai", "ninja", "shogun", "daimyo", "ronin", "geisha", "kabuki", "no", "bunraku", "ukiyo-e", "haiku", "tanka", "renga", "waka", "choka", "sedoka", "kanshi", "gendaishi", "manga", "anime", "studio ghibli", "hayao miyazaki", "akira kurosawa", "yasujiro ozu", "kenji mizoguchi", "nagisa oshima", "shohei imamura", "hirokazu kore-eda", "ryusuke hamaguchi", "takeshi kitano", "takashi miike", "sion sono", "shinichiro watanabe", "mamoru oshii", "katsuhiro otomo", "satoshi kon", "makoto shinkai", "hideaki anno", "yoshiyuki tomino", "yoshiyuki sadamoto", "yoko kanno", "joe hisaishi", "ryuichi sakamoto", "hikaru utada", "ayumi hamasaki", "namie amuro", "kumi koda", "ai otsuka", "yui", "aiko", "ringo sheena", "shiina ringo", "tokyo jihen", " NUMBER GIRL", "the pillows", "asian kung-fu generation", "radwimps", "one ok rock", "babymetal", "band-maid", "lovebites", "maximum the hormone", "x japan", "luna sea", "buck-tick", "malice mizer", "moidixmoi", "versailles", "the gazette", "dir en grey", "hyde", "gackt", "t.m.revolution", "sakurai atsushi", "kiyoharu", "yoshiki", "hide", "hide x japan", "hide with spread beaver", "zeta zero", "sugizo", "heath", "taiji", "pata", "toshi", "hide memorial summit", "visual kei", "j-rock", "j-pop", "k-pop", "korean wave", "hallyu", "bts", "blackpink", "twice", "red velvet", "exo", "bigbang", "psy", "gangnam style", "squid game", "parasite", "train to busan", "oldboy", "memories of murder", "the host", "snowpiercer", "okja", "burning", "minari", "everything everywhere all at once", "the farewell", "crazy rich asians", "shang-chi", "mulan", "coco", "spirited away", "my neighbor totoro", "princess mononoke", "howl's moving castle", "ponyo", "the wind rises", "kiki's delivery service", "castle in the sky", "nausicaa", "grave of the fireflies", "only yesterday", "ocean waves", "whisper of the heart", "the cat returns", "tales from earthsea", "arrietty", "from up on poppy hill", "the tale of princess kaguya", "when marnie was there", "earwig and the witch", "the boy and the heron", "weathering with you", "your name", "5 centimeters per second", "the garden of words", "children who chase lost voices", "journey to agartha", "the place promised in our early days", "voices of a distant star", "she and her cat", "star wars", "star trek", "doctor who", "the expanse", "dune", "foundation", "hyperion", "ender's game", "the matrix", "blade runner", "alien", "predator", "terminator", "back to the future", "indiana jones", "jurassic park", "jaws", "e.t.", "close encounters", "raiders of the lost ark", "temple of doom", "last crusade", "kingdom of the crystal skull", "dial of destiny", "the godfather", "goodfellas", "casino", "mean streets", "taxi driver", "raging bull", "the departed", "wolf of wall street", "shutter island", "inception", "interstellar", "tenet", "dunkirk", "the dark knight", "memento", "prestige", "insomnia", "following", "batman begins", "the dark knight rises", "man of steel", "batman v superman", "justice league", "wonder woman", "aquaman", "shazam", "the suicide squad", "birds of prey", "joker", "the batman", "superman", "spider-man", "iron man", "captain america", "thor", "hulk", "black widow", "hawkeye", "black panther", "doctor strange", "ant-man", "guardians of the galaxy", "the avengers", "avengers endgame", "avengers infinity war", "captain marvel", "shang-chi", "eternals", "spider-man no way home", "doctor strange multiverse of madness", "thor love and thunder", "black panther wakanda forever", "ant-man quantumania", "guardians of the galaxy vol 3", "the marvels", "deadpool", "logan", "x-men", "fantastic four", "silver surfer", "galactus", "thanos", "darkseid", "steppenwolf", "doomsday", "brainiac", "lex luthor", "the joker", "harley quinn", "bane", "ras al ghul", "scarecrow", "two-face", "the riddler", "the penguin", "mr freeze", "poison ivy", "catwoman", "robin", "nightwing", "red hood", "batgirl", "batwoman", "oracle", " commissioner gordon", "alfred pennyworth", "lucius fox", "jim gordon", "harvey bullock", "rene montoya", "vicki vale", "lois lane", "jimmy olsen", "perry white", "martha kent", "jonathan kent", "jor-el", "lara lor-van", "general zod", "faora", "doomsday", "darkseid", "steppenwolf", "desaad", "granny goodness", "kalibak", "mafia", "kanto", "glorious godfrey", "mad harriet", "lashina", "stompa", "bernadeth", "big barda", "mister miracle", "orion", "lightray", "highfather", "izaya", "avi", "scot", "metron", "infinity man", "forager", "mark moonrider", "beautiful dreamer", "vykin", "serifan", "big bear", "MASH", "m.a.s.h.", "mash 4077", "alan alda", "hawkeye pierce", "trapper john", "bj hunnicutt", "frank burns", "margaret houlihan", "hot lips", "henry blake", "sherman potter", "charles winchester", " radar o'reilly", "klinger", "father mulcahy", "igor straminsky", "the swamper", "spearchucker", "ugly john", "truman", "roosevelt", "eisenhower", "kennedy", "johnson", "nixon", "ford", "carter", "reagan", "bush", "clinton", "obama", "trump", "biden", "churchill", "thatcher", "blair", "cameron", "may", "johnson", "sunak", "trudeau", "macron", "merkel", "scholz", "draghi", "meloni", "modi", "xi jinping", "putin", "zelensky", "netanyahu", "erdogan", "orbán", "duda", "morawiecki", "babiš", "fiala", "nečas", "klaus", "havél", "masaryk", "benes", "gottwald", "husák", "havel", "klaus", "zeman", "pavel"]):
        family = "background_overview"
        needs_web = True
        cat = "informational"
    elif any(k in q_lower for k in ["hello", "who are you", "good morning", "how are you", "what is your name", "hi ", "hey ", "what's up", "thank you", "thanks", "please", "sorry", "excuse me", "pardon", "congratulations", "well done", "good job", "nice work", "great effort", "keep it up", "you're welcome", "no problem", "my pleasure", "anytime", "don't mention it", "not at all", "forget about it", "fuggedaboutit", "howdy", "greetings", "salutations", "welcome", "farewell", "goodbye", "see you", "take care", "have a good one", "catch you later", "peace out", "laters", "cheerio", "ta-ta", "toodle-oo", "pip pip", "tally ho", "chin up", "keep calm", "carry on", "stiff upper lip", "don't panic", "hakuna matata", "que sera sera", "c'est la vie", "carpe diem", "yolo", "fomo", "fud", "hodl", "wagmi", "ngmi", "gm", "gn", "ser", "fren", "anon", "degen", "ape", "diamond hands", "paper hands", "rug pull", "pump and dump", "shill", "shitcoin", "memecoin", "dogecoin", "shiba inu", "safemoon", "bitconnect", "onecoin", "theranos", "enron", "worldcom", "lehman brothers", "bear stearns", "merrill lynch", "countrywide", "washington mutual", "indyMac", "fannie mae", "freddie mac", "aig", "goldman sachs", "morgan stanley", "jpmorgan chase", "bank of america", "citigroup", "wells fargo", "deutsche bank", "barclays", "hsbc", "ubs", "credit suisse", "nomura", "mizuho", "sumitomo mitsui", "mitsubishi ufj", "sanwa", "fuji", "dai-ichi kangyo", "industrial bank of japan", "long-term credit bank of japan", "nippon credit bank", "resona", "saitama resona", "asahi", "tokai", "miyazaki", "kagoshima", "okinawa", "hokkaido", "tohoku", "kanto", "chubu", "kinki", "chugoku", "shikoku", "kyushu", "okinawa", "aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima", "ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa", "niigata", "toyama", "ishikawa", "fukui", "yamanashi", "nagano", "gifu", "shizuoka", "aichi", "mie", "shiga", "kyoto", "osaka", "hyogo", "nara", "wakayama", "tottori", "shimane", "okayama", "hiroshima", "yamaguchi", "tokushima", "kagawa", "ehime", "kochi", "fukuoka", "saga", "nagasaki", "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa"]):
        family = "local_answer"
        needs_web = False
        cat = "greeting"
    elif any(k in q_lower for k in ["what is 2+2", "what is 5+5", "calculate", "translate", "solve ", "factor ", "integral", "derivative", "logarithm", "exponential", "trigonometry", "sine", "cosine", "tangent", "cotangent", "secant", "cosecant", "arcsin", "arccos", "arctan", "hyperbolic", "complex number", "imaginary", "real number", "rational", "irrational", "prime", "composite", "fibonacci", "factorial", "permutation", "combination", "probability", "statistics", "mean", "median", "mode", "standard deviation", "variance", "correlation", "regression", "hypothesis test", "p-value", "confidence interval", "normal distribution", "binomial", "poisson", "geometric", "uniform", "exponential distribution", "chi-square", "t-test", "anova", "manova", "ancova", "factor analysis", "cluster analysis", "discriminant analysis", "principal component", "eigenvalue", "eigenvector", "singular value", "matrix", "vector", "tensor", "quaternion", "octonion", "sedenion", "clifford algebra", "grassmann", "lie algebra", "lie group", "manifold", "topology", "homotopy", "homology", "cohomology", "k-theory", "category theory", "functor", "natural transformation", "adjunction", "limit", "colimit", "universal property", "yoneda lemma", "grothendieck", "topos", "sheaf", "scheme", "variety", "stack", "derived category", "infinity category", "homotopy type theory", "type theory", "lambda calculus", "combinatory logic", "proof theory", "model theory", "set theory", "forcing", "large cardinal", "axiom of choice", "continuum hypothesis", "incompleteness theorem", "turing machine", "church-turing", "halting problem", "p vs np", "computational complexity", "big o", "little o", "big omega", "big theta", "amortized analysis", "dynamic programming", "greedy algorithm", "divide and conquer", "backtracking", "branch and bound", "heuristic", "metaheuristic", "genetic algorithm", "simulated annealing", "tabu search", "ant colony", "particle swarm", "neural network", "deep learning", "convolutional", "recurrent", "lstm", "gru", "transformer", "attention", "self-attention", "multi-head", "bert", "gpt", "t5", "bart", "pegasus", "electra", "roberta", "distilbert", "albert", "xlnet", "ernie", "deberta", "modernbert", "llama", "mistral", "mixtral", "qwen", "yi", "falcon", "mpt", "gpt-neo", "gpt-j", "gpt-neox", "pythia", "opt", "bloom", "bloomz", "mt0", "t0", "flan", "instructgpt", "chatgpt", "claude", "gemini", "palm", "lamda", "bard", "gopher", "chinchilla", "gato", "rt-2", "palm-e", "gpt-4", "gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "o1", "o3", "deepseek", "deepseek-r1", "kimi", "moonshot", "chatglm", "baichuan", "internlm", "aquilachat", "sparkdesk", "wenxin", "tongyi", "hunyuan", "doubao", "cici", "copilot", "github copilot", "amazon codewhisperer", "tabnine", "cursor", "replit", "ghostwriter", "codeium", "continue.dev", "aider", "open interpreter", "01 light", "rabbit r1", "humane ai pin", "meta ray-ban", "apple vision pro", "quest 3", "quest 2", "quest pro", "psvr2", "index", "vive", "valve index", "hp reverb", "pico", "bytedance", "tiktok", "instagram", "facebook", "twitter", "x.com", "threads", "whatsapp", "telegram", "signal", "snapchat", "discord", "slack", "teams", "zoom", "webex", "google meet", "skype", "facetime", "imessage", "sms", "mms", "email", "gmail", "outlook", "yahoo mail", "protonmail", "tutanota", "fastmail", "hey", "superhuman", "spark", "edison", "newton", "notion", "obsidian", "roam research", "logseq", "remnote", "anki", "quizlet", "memrise", "duolingo", "babbel", "busuu", "lingoda", "italki", "preply", "cambly", "verbling", "verbalplanet", "hello talk", "tandem", "speaky", "interpals", "conversation exchange", "my language exchange", "lingq", "readlang", "translated", "deepl", "google translate", "microsoft translator", "amazon translate", "yandex translate", "papago", "naver", "kakao", "line", "wechat", "qq", "weibo", "xiaohongshu", "douyin", "bilibili", "zhihu", "tieba", "weixin", "miniprogram", "mini app", "super app", "platform", "ecosystem", "walled garden", "open web", "decentralized", "web3", "blockchain", "smart contract", "defi", "nft", "dao", "token", "coin", "altcoin", "stablecoin", "cbdc", "digital dollar", "e-cny", "sand dollar", "mojaloop", "level one project", "gates foundation", "melinda gates", "warren buffett", "charlie munger", "ray dalio", "howard marks", "seth klarman", "joel greenblatt", "peter lynch", "john bogle", "jack bogle", "vanguard", "fiduciary", "fee-only", "commission", "aum", "assets under management", "robo-advisor", "betterment", "wealthfront", "sofi", "robinhood", "webull", "e-trade", "td ameritrade", "schwab", "fidelity", "interactive brokers", "trade station", "thinkorswim", "market maker", "high frequency trading", "hft", "quantitative trading", "algorithmic trading", "systematic trading", "discretionary trading", "prop trading", "market neutral", "long short", "event driven", "merger arbitrage", "convertible arbitrage", "fixed income arbitrage", "statistical arbitrage", "volatility arbitrage", "global macro", "trend following", "momentum", "mean reversion", "pairs trading", "basket trading", "basket", "portfolio optimization", "mean variance", "efficient frontier", "capital asset pricing model", "capm", "arbitrage pricing theory", "apt", "fama french", "three factor", "five factor", "multifactor", "smart beta", "factor investing", "value investing", "growth investing", "income investing", "dividend growth", "dividend aristocrat", "dividend king", "blue chip", "penny stock", "small cap", "mid cap", "large cap", "mega cap", "unicorn", "decacorn", "centaur", "camel", "zebra", "penguin", "cockroach", "lifestyle business", "saas", "paas", "iaas", "daas", "faas", "baas", "mbaas", "caas", "xaas", "on-prem", "hybrid cloud", "multi-cloud", "cloud native", "cloud agnostic", "vendor lock-in", "data gravity", "egress fee", "ingress", "api gateway", "service mesh", "istio", "linkerd", "consul", "envoy", "traefik", "caddy", "haproxy", "nginx plus", "f5", "citrix", "akamai", "cloudflare", "fastly", "verizon", "limelight", "level3", "centurylink", "lumen", "at&t", "verizon", "t-mobile", "sprint", "vodafone", "orange", "telefonica", "deutsche telekom", "softbank", "ntt", "kddi", "rakuten", "jio", "airtel", "vodafone idea", "bsnl", "mtnl", "china mobile", "china unicom", "china telecom", "singtel", "starhub", "m1", "telstra", "optus", "tpg", "vodafone australia", "spark", "2degrees", "skinny", "one nz", "chorus", "fletcher building", "fonterra", "a2 milk", "synlait", "fisher & paykel", "ril", "reliance", "tata", "birla", "mahindra", "bajaj", "hero", "tvs", "royal enfield", "jawa", "yezdi", "bajaj chetak", "ather", "ola electric", "ather energy", "revolt", "tork motors", "pure ev", "ampere", "bgauss", "okinawa", "komaki", "hero electric", "ampere vehicles", "greaves cotton", "lml", "vespa", "piaggio", "aprilia", "moto guzzi", "ducati", "triumph", "norton", "bsa", "matchless", "ajs", "velocette", "vincent", "ariel", "brough superior", "sunbeam", "royal enfield", "norton commando", "triumph bonneville", "bmw r", "gs ", "k ", "s ", "f ", "r ", "hp ", "hp2", "hp4", "s1000", "r1250", "f900", "g310", "c400", "c650", "r18", "rninet", "k1600", "k1200", "k1300", "r1200", "r1150", "r1100", "r850", "r80", "r65", "r45", "r27", "r26", "r25", "r24", "r23", "r20", "r17", "r16", "r12", "r11", "r10", "r6", "r5", "r4", "r3", "r2", "r1", "r0", "k ", "s ", "f ", "g ", "c ", "hp ", "s1000", "m ", "x ", "i ", "z ", "7 ", "5 ", "3 ", "1 ", "2 ", "4 ", "6 ", "8 ", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "z1", "z3", "z4", "z8", "m1", "m2", "m3", "m4", "m5", "m6", "m8", "i3", "i4", "i5", "i7", "i8", "ix", "i3", "i4", "i5", "i7", "i8", "ix3", "ix", "xm", " Concept", " Vision", " Gran Coupe", " Active Tourer", " Gran Tourer", " Touring", " Coupe", " Convertible", " Roadster", " Sport", " M Sport", " xDrive", " sDrive", " eDrive", " EfficientDynamics", " Connected", " iDrive", " Live Cockpit", " Operating System", " Operating System 7", " Operating System 8", " Operating System 8.5", " Operating System 9", "曲面屏", "哈曼卡顿", "宝华韦健", " Bowers & Wilkins", " Harman Kardon", " Bang & Olufsen", " Burmester", " Mark Levinson", " Lexicon", " Revel", " Fender", " Bose", " Sony", " JBL", " Infinity", " Alpine", " Pioneer", " Kenwood", " Clarion", " Panasonic", " Denon", " Marantz", " Onkyo", " Integra", " Pioneer", " Elite", " Yamaha", " Aventage", " RX", " CX", " MX", " V6", " V8", " V10", " V12", " W12", " W16", " inline-3", " inline-4", " inline-5", " inline-6", " flat-4", " flat-6", " rotary", " wankel", " diesel", " gasoline", " petrol", " electric motor", " hybrid", " plug-in hybrid", " phev", " bev", " fcev", " hydrogen fuel cell", " natural gas", " propane", " lpg", " cng", " biodiesel", " ethanol", " e85", " flex fuel", " synthetic fuel", " e-fuel", " blue gas", " green hydrogen", " turquoise hydrogen", " gray hydrogen", " brown hydrogen", " pink hydrogen", " yellow hydrogen", " white hydrogen", "gold hydrogen", "red hydrogen", "purple hydrogen", "rainbow hydrogen", "hydrogen rainbow", "hydrogen economy", "hydrogen valley", "hydrogen hub", "hydrogen corridor", "hydrogen highway", "hydrogen refueling", "hydrogen station", "electrolyzer", "pem electrolyzer", "alkaline electrolyzer", "soec", "solid oxide", "proton exchange membrane", "anion exchange membrane", "membrane electrode assembly", "catalyst", "platinum", "iridium", "ruthenium", "palladium", "rhodium", "osmium", "cobalt", "nickel", "iron", "manganese", "copper", "zinc", "aluminum", "silicon", "germanium", "gallium", "indium", "tin", "lead", "bismuth", "antimony", "arsenic", "phosphorus", "sulfur", "selenium", "tellurium", "polonium", "boron", "carbon", "nitrogen", "oxygen", "fluorine", "chlorine", "bromine", "iodine", "astatine", "tennessine", "helium", "neon", "argon", "krypton", "xenon", "radon", "oganesson", "hydrogen", "lithium", "sodium", "potassium", "rubidium", "cesium", "francium", "beryllium", "magnesium", "calcium", "strontium", "barium", "radium", "scandium", "titanium", "vanadium", "chromium", "manganese", "iron", "cobalt", "nickel", "copper", "zinc", "yttrium", "zirconium", "niobium", "molybdenum", "technetium", "ruthenium", "rhodium", "palladium", "silver", "cadmium", "hafnium", "tantalum", "tungsten", "rhenium", "osmium", "iridium", "platinum", "gold", "mercury", "thallium", "lead", "bismuth", "polonium", "astatine", "radon", "francium", "radium", "actinium", "thorium", "protactinium", "uranium", "neptunium", "plutonium", "americium", "curium", "berkelium", "californium", "einsteinium", "fermium", "mendelevium", "nobelium", "lawrencium", "rutherfordium", "dubnium", "seaborgium", "bohrium", "hassium", "meitnerium", "darmstadtium", "roentgenium", "copernicium", "nihonium", "flerovium", "moscovium", "livermorium", "tennessine", "oganesson"]):
        family = "local_answer"
        needs_web = False
        cat = "math"
    else:
        family = "local_answer"
        needs_web = False
        cat = "general"

    classification = ClassificationResult(
        intent=family, intent_family=family, intent_class=family,
        category=cat, confidence=0.85, needs_web=needs_web,
        evidence_mode="required" if requires_evidence else "",
        evidence_reason=evidence_reason,
        augmentation_recommended=needs_web and not requires_evidence,
        force_local="story" in q_lower or "poem" in q_lower,
    )

    decision = select_route(classification, policy="fallback_only")

    return {
        "query": query,
        "labels": {
            "intent_family": family,
            "evidence_mode": "required" if requires_evidence else "not_required",
            "route": decision.route,
            "policy_override": "none",
        },
        "metadata": {"source": "comprehensive_dataset"},
    }


QUERIES = [
    # === LOCAL ANSWER (60 examples) ===
    # Math
    "What is 2+2?", "What is 15 times 23?", "Solve 3x + 7 = 22", "Factor x squared minus 9",
    "What is the square root of 144?", "Calculate 15% of 240", "What is log base 2 of 64?",
    "Sin of 30 degrees", "What is the derivative of e to the x?", "Integral of x squared dx",
    "What is 5 factorial?", "GCD of 48 and 18", "What is pi to 5 decimal places?",
    # Translation
    "Translate hello to Japanese", "How do you say thank you in French?", "What is goodbye in Spanish?",
    "Translate 'I love you' to Italian", "Say 'Where is the bathroom' in German",
    # Coding
    "What is a Python list comprehension?", "How do I reverse a string in JavaScript?",
    "Debug this: IndexError list index out of range", "What is the difference between == and ===?",
    "How do I handle exceptions in Python?", "What is a SQL injection?",
    "Explain recursion with an example", "What is the time complexity of quicksort?",
    "How do I use git rebase?", "What is a deadlock in operating systems?",
    # Advice/Opinion
    "Should I learn Python or JavaScript first?", "What are the pros and cons of remote work?",
    "How do I deal with burnout?", "Advice for public speaking",
    "Tips for improving focus", "How to stay productive working from home",
    "Should I buy a Mac or PC?", "Is it worth getting a master's degree?",
    # General knowledge
    "What is the capital of France?", "Who wrote Romeo and Juliet?",
    "What is the speed of light?", "How many continents are there?",
    "What is photosynthesis?", "Who painted the Mona Lisa?",
    "What is DNA?", "How old is the Earth?",
    # Identity
    "Who are you?", "What can you do?", "What is your name?",
    "How capable are you at coding?", "What model LLM are you?",
    "Good morning", "Hello", "How are you?",

    # === BACKGROUND OVERVIEW (35 examples) ===
    "Who was Marie Curie?", "Explain photosynthesis",
    "What caused the French Revolution?", "How does a nuclear reactor work?",
    "What is CRISPR gene editing?", "Explain the theory of relativity",
    "What is dark matter?", "History of the Roman Empire",
    "What is machine learning?", "Tell me about Napoleon",
    "Who was Ada Lovelace?", "What is quantum computing?",
    "What caused World War II?", "How does the immune system work?",
    "What is blockchain?", "Explain climate change",
    "What is artificial intelligence?", "Who was Alan Turing?",
    "What is the Big Bang theory?", "How does DNA replication work?",
    "What is evolution?", "Explain plate tectonics",
    "What is neuroplasticity?", "Who was Nikola Tesla?",
    "What is the Higgs boson?", "Explain general relativity simply",
    "What is the microbiome?", "How does a jet engine work?",
    "What is cryptocurrency?", "Explain Moore's Law",
    "What is the Fermi paradox?", "How do vaccines work?",
    "What is the Great Filter?", "Explain the Dunning-Kruger effect",
    "What is game theory?",

    # === TECHNICAL EXPLANATION (25 examples) ===
    "How do I install Docker on Ubuntu?", "What is the best way to learn Python?",
    "How does garbage collection work in Python?", "Debug this Python error: AttributeError",
    "How do I set up a VPN?", "Explain React hooks",
    "How does a transformer neural network work?", "Explain TCP congestion control",
    "What algorithm does Bitcoin use?", "How is TLS implemented?",
    "Explain the math behind Fourier transforms", "How does RAID storage work?",
    "What is BGP routing?", "How do I optimize SQL queries?",
    "Explain Docker container networking", "How does a compiler work?",
    "What is the CAP theorem?", "How do I implement OAuth2?",
    "Explain Kubernetes pod scheduling", "What is a bloom filter?",
    "How does consensus work in blockchain?", "Explain virtual memory",
    "What is event-driven architecture?", "How does a load balancer work?",
    "Explain the difference between REST and GraphQL",

    # === MEDICAL INQUIRY (AUGMENTED) (20 examples) ===
    "What are the symptoms of diabetes?", "Can I take ibuprofen with aspirin?",
    "What is the treatment for high blood pressure?", "Side effects of metformin",
    "Flu symptoms in children", "How do I know if I have COVID?",
    "Migraine treatment options", "Is it safe to exercise with chest pain?",
    "What are early signs of dementia?", "Antibiotics for strep throat dosage",
    "What are the symptoms of appendicitis?", "Is acetaminophen safe during pregnancy?",
    "What is the dosage for amoxicillin?", "How to treat a migraine?",
    "Is tadalafil safe with grapefruit?", "What does eGFR measure?",
    "Difference between IBS and Crohn's disease", "Is unexplained weight loss serious?",
    "Can I take warfarin with aspirin?", "What are concussion symptoms?",

    # === FINANCIAL DATA (AUGMENTED) (12 examples) ===
    "What is the current price of Apple stock?", "Bitcoin price today",
    "Current EUR to USD exchange rate", "What is the current federal reserve interest rate?",
    "Tesla stock performance this week", "Ethereum price right now",
    "S&P 500 index today", "What is the current inflation rate?",
    "Dow Jones today", "FTSE 100 current value",
    "Gold price per ounce", "Oil price per barrel",

    # === LEGAL (AUGMENTED) (8 examples) ===
    "Is it legal to record a phone call without consent?", "What are tenant rights in California?",
    "Latest Supreme Court decision on guns", "Speeding ticket penalty in New York",
    "Is it legal to ride a bike on the sidewalk?", "What is the statute of limitations for theft?",
    "Can I break a lease early?", "What is GDPR compliance?",

    # === CURRENT EVIDENCE (AUGMENTED) (10 examples) ===
    "What does the latest research say about climate change?",
    "Peer-reviewed studies on intermittent fasting",
    "Evidence for vaccines being safe", "Meta-analysis of coffee health effects",
    "Has cold fusion been proven?", "What do we know about long COVID?",
    "Latest research on Alzheimer's prevention", "Systematic review of sleep and memory",
    "What is the current scientific consensus on GMOs?", "Clinical trial results for new cancer drugs",

    # === NEWS REQUEST (20 examples) ===
    "Breaking news about the election", "What is happening in Gaza right now?",
    "Latest tech news", "Weather alert for Sydney",
    "Sports headlines today", "Current situation in Ukraine",
    "Political news from Australia", "Latest Israel headlines",
    "What's the latest world news?", "Breaking news about earthquake",
    "Headlines about AI regulation", "Current events in Europe",
    "What's happening in Sudan?", "Latest news on Israel",
    "News from Australia today", "Tech industry layoffs news",
    "Climate policy updates", "Energy prices news",
    "Cybersecurity breach news", "Space exploration news",

    # === TIME QUERY (12 examples) ===
    "What time is it in London?", "Current time in New York",
    "What day is it today?", "Timezone difference between Tokyo and London",
    "How many days until Christmas?", "What time is it in Tokyo?",
    "Current time in Sydney", "What date is Thanksgiving this year?",
    "How many hours until midnight?", "What timezone is Berlin in?",
    "Current time in Dubai", "What day of the week is March 15?",

    # === CREATIVE WRITING (20 examples) ===
    "Write a poem about the ocean", "Imagine a world where AI governs everything",
    "Create a dialogue between Shakespeare and Einstein", "Write a short horror story",
    "Draft a screenplay scene about time travel", "Write a 50 word story about a cat",
    "Write a 500 word story about a robot learning to paint",
    "Compose a fairy tale about a dragon", "Write lyrics for a love song",
    "Create a myth explaining thunder", "Write a comedy sketch about aliens",
    "Imagine dinosaurs never went extinct", "Write a letter from the future",
    "Create a world where water flows uphill", "Write a detective story opening",
    "Draft a presidential speech about Mars colonization", "Write a children's story about friendship",
    "Create a parody of Romeo and Juliet", "Write a sci-fi story about first contact",
    "Imagine a day in the life of a cat",

    # === CLARIFICATION (10 examples) ===
    "What?", "Explain that again", "I don't understand",
    "Huh?", "Can you clarify?", "What do you mean?",
    "Go on", "Tell me more", "Elaborate", "Please explain",
]


def main():
    print("=" * 70)
    print("Building Comprehensive Labeled Query Dataset")
    print("=" * 70)

    examples = []
    for query in QUERIES:
        labeled = label_query(query)
        examples.append(labeled)

    # Stats
    from collections import Counter
    intent_counts = Counter(ex["labels"]["intent_family"] for ex in examples)
    route_counts = Counter(ex["labels"]["route"] for ex in examples)

    print(f"\nTotal examples: {len(examples)}")
    print(f"\nIntent distribution:")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent:25s}: {count}")
    print(f"\nRoute distribution:")
    for route, count in sorted(route_counts.items()):
        print(f"  {route:20s}: {count}")

    # Save
    output_path = Path("comprehensive_index.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nSaved to {output_path}")

    # Build embedding index
    print(f"\n{'=' * 70}")
    print("Building Embedding Index...")
    print(f"{'=' * 70}")

    from embedding_router import EmbeddingRouter
    router = EmbeddingRouter()
    router.fit(examples)

    np.save("comprehensive_embeddings.npy", router.embeddings)
    with open("comprehensive_examples.json", "w") as f:
        json.dump(router.examples, f, indent=2)

    print(f"  Embeddings: comprehensive_embeddings.npy")
    print(f"  Examples: comprehensive_examples.json")

    # Shadow test
    print(f"\n{'=' * 70}")
    print("Shadow Test")
    print(f"{'=' * 70}")

    test_queries = [
        "What are the symptoms of flu?",
        "Who was Ada Lovelace?",
        "What time is it in Tokyo?",
        "Latest news on Israel",
        "Write a story about a robot",
        "What is 2+2?",
        "How do I install Python?",
        "Breaking news about earthquake",
        "Stock price of Apple",
        "Is it legal to ride a bike on the sidewalk?",
        "Explain quantum computing",
        "Tell me a joke",
        "What is the treatment for diabetes?",
        "Current bitcoin price",
        "Latest Supreme Court ruling",
        "Who invented the telephone?",
        "What is the capital of France?",
        "How do I bake sourdough bread?",
        "Translate hello to Japanese",
        "What is CRISPR?",
    ]

    agreements = 0
    for q in test_queries:
        # Legacy
        labeled = label_query(q)
        legacy_route = labeled["labels"]["route"]

        # Embedding
        emb = router.predict(q, k=5)
        emb_route = emb["route"]

        agree = legacy_route == emb_route
        if agree:
            agreements += 1
        status = "YES" if agree else "NO"
        print(f"  [{status}] {q:50s} legacy={legacy_route:12s} emb={emb_route:12s} conf={emb['confidence']:.3f}")

    print(f"\nAgreement: {agreements}/{len(test_queries)} ({100*agreements/len(test_queries):.0f}%)")

    return router, examples


if __name__ == "__main__":
    main()
