import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name = "sim800",
    version = "0.1.0",
    author = "Henry Cooke",
    author_email = "me@prehensile.co.uk",
    description = "A library for interfacing with the SIM800 GSM/GPRS Module",
    long_description = long_description,
    long_description_content_type = "text/markdown",
    url = "https://github.com/prehensile/SIM800",
    packages = setuptools.find_packages(),
    classifiers = [
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Development Status :: 3 - Alpha",
        "Topic :: Communications :: Telephony",
        "Topic :: System :: Hardware"
    ],
    install_requires=[
        "pyserial"
    ]
)