from setuptools import find_packages, setup

package_name = "rover_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/bringup.launch.py", "launch/mapping.launch.py"]),
        (f"share/{package_name}/params", ["params/bringup.yaml", "params/nav2_filters.yaml", "params/ekf.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Rover Dev",
    maintainer_email="dev@rover.local",
    description="Bringup package for rover stack orchestration.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "bringup_node = rover_bringup.bringup_node:main",
            "sensor_stamp_relay = rover_bringup.sensor_stamp_relay:main",
        ],
    },
)
