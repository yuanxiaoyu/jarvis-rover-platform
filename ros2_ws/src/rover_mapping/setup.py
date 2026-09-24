from setuptools import find_packages, setup

package_name = "rover_mapping"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/params", ["params/mapping.yaml", "params/slam_toolbox_online_async.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Rover Dev",
    maintainer_email="dev@rover.local",
    description="Mapping bridge for occupancy + semantic 3D reconstruction metadata.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "mapping_node = rover_mapping.mapping_node:main",
        ],
    },
)
