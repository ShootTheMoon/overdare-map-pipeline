--!strict
-- Rebuilds the invisible architectural collision proxies for the imported
-- GY Gyeongbokgung master map and normalizes its existing walkable ground.
-- Proxy source bounds are Blender meters; generated transforms are absolute
-- OVERDARE world-space centimeters with zero rotation.

local CollisionRecipe = {}

local ROOT_NAME = "GY_ArchitectureCollision"
local GROUND_NAME = "GY_WalkableGroundCollision"
local PROXY_COLOR = Color3.fromRGB(96, 100, 104)

-- Imported map alignment anchors supplied from the Blender master and the
-- Studio MeshPart AABB. Blender Y maps to Studio Z, and Blender Z maps to Studio Y.
local BLENDER_MASTER_CENTER = Vector3.new(0, 135, 8.015)
local STUDIO_MESH_CENTER = Vector3.new(-33.686939, 836.500488, 305.237427)

-- Master UCX components 01-24 in Blender meters.
local PROXIES = {
	{ name = "GY_UCX_01", center = Vector3.new(-11, 30, 2.1), size = Vector3.new(14, 9, 4.2) },
	{ name = "GY_UCX_02", center = Vector3.new(11, 30, 2.1), size = Vector3.new(14, 9, 4.2) },
	{ name = "GY_UCX_03", center = Vector3.new(-47, 30, 2.0), size = Vector3.new(58, 4, 4.0) },
	{ name = "GY_UCX_04", center = Vector3.new(47, 30, 2.0), size = Vector3.new(58, 4, 4.0) },
	{ name = "GY_UCX_05", center = Vector3.new(-9.5, 95, 1.8), size = Vector3.new(11, 7, 3.6) },
	{ name = "GY_UCX_06", center = Vector3.new(9.5, 95, 1.8), size = Vector3.new(11, 7, 3.6) },
	{ name = "GY_UCX_07", center = Vector3.new(-44, 95, 1.8), size = Vector3.new(58, 3, 3.6) },
	{ name = "GY_UCX_08", center = Vector3.new(44, 95, 1.8), size = Vector3.new(58, 3, 3.6) },
	{ name = "GY_UCX_09", center = Vector3.new(-9, 150, 1.7), size = Vector3.new(10, 7, 3.4) },
	{ name = "GY_UCX_10", center = Vector3.new(9, 150, 1.7), size = Vector3.new(10, 7, 3.4) },
	{ name = "GY_UCX_11", center = Vector3.new(-42.5, 150, 1.7), size = Vector3.new(57, 3, 3.4) },
	{ name = "GY_UCX_12", center = Vector3.new(42.5, 150, 1.7), size = Vector3.new(57, 3, 3.4) },
	{ name = "GY_UCX_13", center = Vector3.new(0, 226, 0.75), size = Vector3.new(46, 36, 1.5) },
	{ name = "GY_UCX_14", center = Vector3.new(0, 226, 1.65), size = Vector3.new(38, 28, 0.8) },
	{ name = "GY_UCX_15", center = Vector3.new(0, 226, 5.0), size = Vector3.new(29, 20, 6.0) },
	{ name = "GY_UCX_16", center = Vector3.new(0, 204, 0.75), size = Vector3.new(8, 7.9392, 1.7339) },
	{ name = "GY_UCX_17", center = Vector3.new(0, 208.5, 1.65), size = Vector3.new(8, 5.9696, 1.3866) },
	{ name = "GY_UCX_18", center = Vector3.new(-37, 196, 1.5), size = Vector3.new(5, 92, 3.0) },
	{ name = "GY_UCX_19", center = Vector3.new(37, 196, 1.5), size = Vector3.new(5, 92, 3.0) },
	{ name = "GY_UCX_20", center = Vector3.new(-82, 155, 1.8), size = Vector3.new(3, 210, 3.6) },
	{ name = "GY_UCX_21", center = Vector3.new(82, 155, 1.8), size = Vector3.new(3, 210, 3.6) },
	{ name = "GY_UCX_22", center = Vector3.new(0, 260, 1.8), size = Vector3.new(167, 3, 3.6) },
	{ name = "GY_UCX_23", center = Vector3.new(-58, 211, 0.75), size = Vector3.new(24, 17, 1.5) },
	{ name = "GY_UCX_24", center = Vector3.new(-40.5, 211, 0.45), size = Vector3.new(11, 3, 0.9) },
}

local function blenderCenterToStudio(center)
	return Vector3.new(
		STUDIO_MESH_CENTER.X + center.X * 100,
		STUDIO_MESH_CENTER.Y + (center.Z - BLENDER_MASTER_CENTER.Z) * 100,
		STUDIO_MESH_CENTER.Z - (center.Y - BLENDER_MASTER_CENTER.Y) * 100
	)
end

local function blenderSizeToStudio(size)
	return Vector3.new(size.X * 100, size.Z * 100, size.Y * 100)
end

local function configureCollisionPart(part)
	part.Shape = "Block"
	part.Anchored = true
	part.Transparency = 1
	part.CanCollide = true
	part.CanQuery = true
	part.CanTouch = true
	part.CastShadow = false
	-- OVERDARE's dedicated invisible-wall profile explicitly blocks Pawn capsules.
	part.CollisionProfile = "InvisibleWall"
	part.Color = PROXY_COLOR
	part.Material = "Basic"
end

CollisionRecipe.OnGenerate = function(parameters, targetContainer)
	-- Replace only this recipe's stable root; visual meshes, spawn points, and
	-- unrelated Workspace instances are deliberately left untouched.
	local previousRoot = workspace:FindFirstChild(ROOT_NAME)
	if previousRoot then
		previousRoot:Destroy()
	end

	-- Component 25 is represented by the pre-existing flat walkable ground Part.
	-- Update it in place so its GUID remains stable and no duplicate is produced.
	local ground = workspace:FindFirstChild(GROUND_NAME)
	if ground and ground:IsA("BasePart") then
		ground.CFrame = CFrame.new(-33.6869, 20.0005, 305.2374)
		ground.Size = Vector3.new(18000, 30, 31000)
		ground.Anchored = true
		ground.Transparency = 1
		ground.CanCollide = true
		ground.CanQuery = true
		ground.CanTouch = true
		ground.CollisionProfile = "BlockAll"
	end

	local root = Instance.new("Model")
	root.Name = ROOT_NAME

	for _, proxyData in PROXIES do
		local proxy = Instance.new("Part")
		proxy.Name = proxyData.name
		local center = blenderCenterToStudio(proxyData.center)
		proxy.CFrame = CFrame.new(center.X, center.Y, center.Z)
		proxy.Size = blenderSizeToStudio(proxyData.size)
		configureCollisionPart(proxy)
		proxy.Parent = root
	end

	root.Parent = targetContainer
end

return CollisionRecipe
