from setuptools import find_packages, setup

package_name = "rover_ai_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/params", ["params/ai_bridge.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Rover Dev",
    maintainer_email="dev@rover.local",
    description="AI bridge for browser prompts to rover tasks.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "ai_bridge_node = rover_ai_bridge.ai_bridge_node:main",
        ],
    },
)
