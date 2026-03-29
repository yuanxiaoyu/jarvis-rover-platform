from setuptools import find_packages, setup

package_name = "rover_vision"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/params", ["params/vision.yaml"]),
    ],
    install_requires=["setuptools"],
    extras_require={
        "yolo": [
            "numpy>=1.26.0",
            "pillow>=10.0.0",
            "ultralytics>=8.2.0",
        ]
    },
    zip_safe=True,
    maintainer="Rover Dev",
    maintainer_email="dev@rover.local",
    description="Vision package for YOLO-style garbage detection, capture persistence, and API reporting.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "garbage_detection_node = rover_vision.garbage_detection_node:main",
        ],
    },
)
