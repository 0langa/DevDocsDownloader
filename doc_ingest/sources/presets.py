from __future__ import annotations

PRESETS: dict[str, list[str]] = {
    "webapp": [
        "HTML", "CSS", "JavaScript", "TypeScript", "HTTP",
        "Node.js", "Express", "React", "Vue.js", "Svelte",
        "Tailwind CSS", "PostgreSQL", "nginx", "Docker", "Git",
        "Web APIs", "WebAssembly",
    ],
    "frontend": [
        "HTML", "CSS", "JavaScript", "TypeScript",
        "React", "Vue.js", "Svelte", "Angular",
        "Tailwind CSS", "Web APIs",
    ],
    "backend": [
        "Python", "Go", "Rust", "Java", "Node.js",
        "PostgreSQL", "Redis", "SQLite", "Docker", "Kubernetes",
        "nginx", "HTTP",
    ],
    "data": [
        "Python", "NumPy", "pandas", "Matplotlib",
        "scikit-learn", "TensorFlow", "PyTorch",
        "PostgreSQL", "SQLite", "R",
    ],
    "mobile": [
        "Swift", "Kotlin", "Dart", "React Native",
        "JavaScript", "TypeScript",
    ],
    "systems": [
        "C", "C++", "Rust", "Go", "Bash",
    ],
    "devops": [
        "Bash", "Docker", "Kubernetes", "Ansible",
        "Terraform", "nginx", "Git", "HTTP",
    ],
    "python-stack": [
        "Python", "Django", "Flask", "FastAPI",
        "SQLAlchemy", "pandas", "NumPy", "pytest",
        "PostgreSQL", "Redis",
    ],
}
