"""The hard skills a posting can ask for: one enum, `HardSkill`, that the models answer with.

Built from Djinni's own skill tags in the 2025–2026 Python postings, where the most common 60
tags make up 89% of all uses. A named technology keeps an id of its own, so Django and Flask
stay apart. A practice is one id however postings word it: REST, OpenAPI and API integration
are all `rest_api`, and unit, integration and automated tests are all `testing`. Every AWS
service is `aws`. Anything else is `other`, and the requirement's `name` says what it is.

Each skill lists the names postings use for it, the first being the one to show. The
labelling page searches them.
"""

from enum import StrEnum

AREAS: dict[str, dict[str, tuple[str, ...]]] = {
    "Languages": {
        "python": ("Python",),
        "sql": ("SQL", "SQL початковий рівень", "T-SQL", "PL/SQL"),
        "javascript": ("JavaScript", "JS"),
        "typescript": ("TypeScript", "TS"),
        "go": ("Go", "Golang"),
        "java": ("Java",),
        "kotlin": ("Kotlin",),
        "csharp": ("C#", ".NET", "C# / .NET", "ASP.NET"),
        "cpp": ("C++", "C/C++", "C"),
        "rust": ("Rust",),
        "php": ("PHP",),
        "ruby": ("Ruby",),
        "scala": ("Scala",),
        "bash": ("Bash", "Shell", "Bash scripting", "shell scripting"),
    },
    "Backend": {
        "django": ("Django", "Django ORM"),
        "drf": ("Django REST Framework", "DRF"),
        "fastapi": ("FastAPI",),
        "flask": ("Flask",),
        "aiohttp": ("aiohttp",),
        "sqlalchemy": ("SQLAlchemy", "Alembic", "SQLModel"),
        "pydantic": ("Pydantic",),
        "nodejs": ("Node.js", "NodeJS", "Express", "NestJS", "Nest.js"),
        "async_programming": (
            "Async programming",
            "asyncio",
            "Asynchronous Programming",
            "concurrency",
            "Multithreading",
            "multiprocessing",
        ),
    },
    "APIs": {
        "rest_api": (
            "REST APIs",
            "REST API",
            "RESTful",
            "REST",
            "OpenAPI",
            "Swagger",
            "API Integration",
            "Web services",
            "third-party APIs",
        ),
        "graphql": ("GraphQL",),
        "grpc": ("gRPC", "Protobuf"),
        "websockets": ("WebSockets", "WebSocket", "Socket.IO"),
    },
    "Databases": {
        "postgresql": ("PostgreSQL", "Postgres"),
        "mysql": ("MySQL", "MariaDB"),
        "mongodb": ("MongoDB", "Mongo"),
        "redis": ("Redis",),
        "elasticsearch": ("Elasticsearch", "OpenSearch"),
        "clickhouse": ("ClickHouse",),
        "nosql": ("NoSQL", "Cassandra"),
        "orm": ("ORM",),
        "database_design": (
            "Database design",
            "Database Design and Architecture",
            "schema design",
            "query optimization",
            "indexing",
        ),
    },
    "Queues": {
        "kafka": ("Kafka", "Apache Kafka"),
        "rabbitmq": ("RabbitMQ", "AMQP"),
        "celery": ("Celery",),
        "message_queues": ("Message queues", "message brokers", "MQTT", "NATS"),
    },
    "Cloud": {
        "aws": (
            "AWS",
            "Amazon Web Services",
            "AWS Lambda",
            "AWS S3",
            "EC2",
            "AWS ECS",
            "AWS EKS",
            "AWS DynamoDB",
            "AWS RDS",
            "AWS SQS",
            "AWS SNS",
            "AWS Step Functions",
            "AWS Fargate",
        ),
        "gcp": ("GCP", "Google Cloud", "Google Cloud Run", "Cloud Functions"),
        "azure": ("Azure", "Microsoft Azure"),
        "cloud": ("Cloud platforms", "Cloud Computing", "Serverless"),
    },
    "DevOps": {
        "docker": ("Docker", "Docker Compose", "containers"),
        "kubernetes": ("Kubernetes", "K8s", "Helm", "GKE"),
        "terraform": ("Terraform", "IaC", "Infrastructure as Code", "CloudFormation", "Pulumi"),
        "ci_cd": (
            "CI/CD",
            "GitHub Actions",
            "GitLab CI",
            "Gitlab CI/CD",
            "Jenkins",
            "Bamboo",
            "Microsoft Azure DevOps",
        ),
        "linux": ("Linux", "Unix", "Ubuntu"),
        "nginx": ("Nginx", "web servers", "Gunicorn", "uWSGI"),
        "observability": (
            "Monitoring and logging",
            "monitoring",
            "logging",
            "Grafana",
            "Prometheus",
            "Sentry",
            "ELK",
            "Datadog",
            "OpenTelemetry",
        ),
        "networking": ("Networking", "HTTP/HTTPS", "HTTP", "TCP/IP", "UDP", "DNS"),
    },
    "Testing": {
        "testing": (
            "Testing",
            "unit tests",
            "Unit Testing",
            "integration tests",
            "e2e tests",
            "TDD",
            "Automation Testing (AQA)",
            "API Testing",
            "test automation",
        ),
        "pytest": ("pytest", "unittest"),
        "selenium": ("Selenium",),
        "playwright": ("Playwright", "Puppeteer"),
    },
    "Design & architecture": {
        "software_design": (
            "Software design",
            "OOP",
            "SOLID",
            "design patterns",
            "clean code",
            "refactoring",
        ),
        "software_architecture": (
            "Software architecture",
            "Microservices",
            "Distributed Systems",
            "system design",
            "Event Driven Architecture",
            "Domain-Driven Design",
            "Clean Architecture",
            "scalability",
            "high load",
        ),
        "algorithms": ("Algorithms and data structures", "Алгоритми та структури даних"),
    },
    "ML & data science": {
        "machine_learning": ("Machine learning", "ML", "AI/ML", "deep learning", "neural networks"),
        "nlp": ("NLP", "natural language processing"),
        "computer_vision": ("Computer Vision", "OpenCV", "image processing"),
        "pandas": ("Pandas",),
        "numpy": ("NumPy",),
        "scikit_learn": ("scikit-learn", "sklearn"),
        "pytorch": ("PyTorch",),
        "tensorflow": ("TensorFlow", "Keras"),
        "data_analysis": ("Data analysis", "Обробка даних", "візуалізація даних", "Jupyter"),
        "mlops": ("MLOps", "MLflow", "Kubeflow", "model deployment"),
    },
    "LLM & GenAI": {
        "ai": ("AI", "Штучний інтелект (AI)", "artificial intelligence"),
        "llm": (
            "LLMs",
            "LLM",
            "GenAI",
            "Generative AI",
            "OpenAI API",
            "Prompt Engineering",
            "fine-tuning",
            "Claude",
            "Llama",
            "Mistral",
        ),
        "rag": (
            "RAG",
            "vector databases",
            "embeddings",
            "pgvector",
            "Pinecone",
            "Qdrant",
            "LlamaIndex",
        ),
        "ai_agents": (
            "AI agents",
            "MCP",
            "LangGraph",
            "CrewAI",
            "PydanticAI",
            "Google ADK",
            "function calling",
        ),
        "langchain": ("LangChain", "Langsmith"),
        "hugging_face": ("Hugging Face", "Transformers"),
        "ai_coding_tools": (
            "AI coding tools",
            "Cursor",
            "GitHub Copilot",
            "Claude Code",
            "Codex",
            "AI інструменти",
        ),
    },
    "Data engineering": {
        "etl": ("ETL", "ELT", "data pipelines", "Data Engineering"),
        "airflow": ("Airflow", "Apache Airflow"),
        "spark": ("Spark", "Apache Spark", "PySpark", "Hadoop", "Big Data"),
        "data_warehouse": (
            "Data warehouses",
            "Snowflake",
            "Google BigQuery",
            "Redshift",
            "Databricks",
            "dbt",
        ),
    },
    "Web scraping": {
        "web_scraping": (
            "Web scraping",
            "Scrapy",
            "BeautifulSoup",
            "lxml",
            "XPath",
            "web crawling",
        ),
    },
    "Frontend": {
        "react": ("React", "React.js", "Redux", "React Query", "Next.js"),
        "angular": ("Angular",),
        "vue": ("Vue", "Vue.js", "Nuxt"),
        "html_css": ("HTML/CSS", "HTML", "CSS", "SCSS", "Bootstrap", "Tailwind CSS"),
    },
    "Security": {
        "security": (
            "Security",
            "OAuth 2.0",
            "JWT",
            "authentication",
            "authorization",
            "OWASP",
            "encryption",
        ),
    },
    "Tools & process": {
        "git": ("Git", "GitHub", "GitLab", "Bitbucket"),
        "agile": (
            "Agile",
            "Scrum",
            "Kanban",
            "Agile Project Management",
            "Jira",
            "Confluence",
            "SDLC",
        ),
    },
}

OTHER = "other"

HardSkill = StrEnum(  # type: ignore[misc]  # built from AREAS, so the two can't drift apart
    "HardSkill",
    [(skill, skill) for skills in AREAS.values() for skill in skills] + [(OTHER, OTHER)],
)

MERGED = {
    skill: names
    for skills in AREAS.values()
    for skill, names in skills.items()
    if skill in ("rest_api", "testing", "software_design", "software_architecture", "aws", "llm")
}
"""The ids that stand for many words, which the models are told about in the schema."""
