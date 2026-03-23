from setuptools import setup, find_packages

setup(
    name="occhi-di-falco",
    version="2.0.0",
    description="Real-time 888 Poker Data Extractor",
    author="Occhi di Falco Team",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.9",
    install_requires=[
        "mss>=9.0.1",
        "pyautogui>=0.9.54",
        "opencv-python>=4.8.0",
        "numpy>=1.24.0",
        "pytesseract>=0.3.10",
        "psutil>=5.9.0",
        "rich>=13.0.0",
        "colorlog>=6.7.0",
    ],
    extras_require={
        "ocr": ["easyocr>=1.7.1"],
        "dev": ["pytest>=7.4.0", "pytest-cov>=4.1.0", "pytest-mock>=3.11.0"],
    },
    entry_points={
        "console_scripts": [
            "occhi-di-falco=main:main",
        ],
    },
)
