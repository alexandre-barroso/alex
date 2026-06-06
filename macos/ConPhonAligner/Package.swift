// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ConPhonAligner",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "ConPhonAligner", targets: ["ConPhonAligner"])
    ],
    targets: [
        .target(name: "ConPhonAlignerCore"),
        .executableTarget(
            name: "ConPhonAligner",
            dependencies: ["ConPhonAlignerCore"]
        ),
        .testTarget(
            name: "ConPhonAlignerCoreTests",
            dependencies: ["ConPhonAlignerCore"]
        )
    ]
)
