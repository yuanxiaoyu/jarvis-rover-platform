from setuptools import find_packages, setup

package_name = "rover_safety"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/params", ["params/safety.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Rover Dev",
    maintainer_email="dev@rover.local",
    description="Safety layer for keepout masks, emergency stop, and obstacle throttling.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "safety_node = rover_safety.safety_node:main",
        ],
    },
)
